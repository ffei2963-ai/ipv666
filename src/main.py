import asyncio
import signal
import sys

from telegram import Update

from src.agent.health_checker import HealthChecker
from src.agent.intent_parser import IntentParser
from src.agent.orchestrator import Orchestrator
from src.bot.telegram_bot import TelegramBot
from src.db.database import init_db, get_db
from src.llm.ollama_client import OllamaClient
from src.security.auth import AuthManager
from src.utils.config import load_config
from src.utils.logger import logger


class IPv666App:
    def __init__(self):
        self.config = load_config()
        self.orchestrator: Orchestrator = None
        self.ollama: OllamaClient = None
        self.intent_parser: IntentParser = None
        self.auth_manager: AuthManager = None
        self.bot: TelegramBot = None
        self.health_checker: HealthChecker = None
        self._running = False

    async def start(self):
        logger.info("=" * 50)
        logger.info("IPv666 Starting...")
        logger.info("=" * 50)

        await init_db()

        admin_ids = self.config.get("telegram", {}).get("admin_ids", [])
        self.auth_manager = AuthManager(admin_ids=admin_ids)
        await self.auth_manager.add_admins_from_env()

        ollama_config = self.config.get("ollama", {})
        self.ollama = OllamaClient(
            host=ollama_config.get("host", "127.0.0.1:11434"),
            model=ollama_config.get("model", "qwen2:0.5b"),
            timeout=ollama_config.get("timeout", 120),
        )

        ollama_healthy = await self.ollama.health_check()
        if not ollama_healthy:
            logger.warning("Ollama health check failed. AI features may not work.")
        else:
            logger.info("Ollama service healthy.")

        self.intent_parser = IntentParser(self.ollama)

        self.orchestrator = Orchestrator(self.config)
        await self.orchestrator.initialize()

        agent_config = self.config.get("agent", {})
        self.health_checker = HealthChecker(
            interval=agent_config.get("health_check_interval", 60),
            timeout=agent_config.get("health_check_timeout", 10),
            max_failures=agent_config.get("max_consecutive_failures", 3),
        )

        async def auto_restart_proxy(proxy):
            try:
                await self.orchestrator.xray_manager.restart()
                from src.proxy.verifier import ProxyVerifier
                verifier = ProxyVerifier()
                if await verifier.verify(proxy):
                    try:
                        db = await get_db()
                        await db.execute(
                            "UPDATE proxies SET status='active', verify_count=0 WHERE id=?",
                            (proxy.id,)
                        )
                        await db.commit()
                        await db.close()
                    except Exception as db_err:
                        logger.error(f"DB update error in auto-repair: {db_err}")
                    logger.info(f"Auto-repair: proxy {proxy.id} restored")
                else:
                    logger.warning(f"Auto-repair: proxy {proxy.id} still failing")
            except Exception as e:
                logger.error(f"Auto-repair error for proxy {proxy.id}: {e}")

        self.health_checker.set_restart_callback(auto_restart_proxy)
        await self.health_checker.start()

        telegram_config = self.config.get("telegram", {})
        bot_token = telegram_config.get("bot_token", "")
        if not bot_token:
            logger.error("No Telegram bot token configured! Set TELEGRAM_BOT_TOKEN environment variable.")
            logger.info("Running in health-check-only mode...")
            self._running = True
            while self._running:
                await asyncio.sleep(1)
            return

        self.bot = TelegramBot(
            token=bot_token,
            orchestrator=self.orchestrator,
            intent_parser=self.intent_parser,
            auth_manager=self.auth_manager,
        )
        self.bot.build_app()

        logger.info("IPv666 fully started. Bot is listening...")
        await self.bot.app.initialize()
        await self.bot.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await self.bot.app.start()
        self._running = True

        while self._running:
            await asyncio.sleep(1)

    async def shutdown(self):
        logger.info("Shutting down IPv666...")
        self._running = False

        if self.bot and self.bot.app:
            try:
                await self.bot.app.updater.stop()
            except Exception:
                pass
            try:
                await self.bot.app.stop()
            except Exception:
                pass

        if self.health_checker:
            await self.health_checker.stop()

        if self.orchestrator:
            await self.orchestrator.shutdown()

        logger.info("IPv666 shutdown complete.")


def main():
    app = IPv666App()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        task = asyncio.ensure_future(app.start())
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.ensure_future(app.shutdown()))
            except NotImplementedError:
                signal.signal(sig, lambda s, f: asyncio.ensure_future(app.shutdown()))
        await task

    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        pass
    finally:
        try:
            loop.run_until_complete(app.shutdown())
        except Exception:
            pass
        loop.close()


if __name__ == "__main__":
    main()
