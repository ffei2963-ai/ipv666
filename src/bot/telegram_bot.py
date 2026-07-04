from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from src.agent.intent_parser import IntentParser
from src.agent.orchestrator import Orchestrator
from src.security.auth import AuthManager
from src.utils.logger import logger


class TelegramBot:
    def __init__(self, token: str, orchestrator: Orchestrator, intent_parser: IntentParser,
                 auth_manager: AuthManager):
        self.token = token
        self.orchestrator = orchestrator
        self.intent_parser = intent_parser
        self.auth_manager = auth_manager
        self.app: Application = None

    def build_app(self) -> Application:
        self.app = Application.builder().token(self.token).build()
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("create", self._cmd_create))
        self.app.add_handler(CommandHandler("list", self._cmd_list))
        self.app.add_handler(CommandHandler("delete", self._cmd_delete))
        self.app.add_handler(CommandHandler("stats", self._cmd_stats))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self.app.add_error_handler(self._error_handler)
        return self.app

    async def _check_auth(self, update: Update) -> bool:
        user_id = str(update.effective_user.id)
        if not await self.auth_manager.is_authorized(user_id):
            await update.message.reply_text(
                "Access denied. You are not authorized to use this bot.\n"
                "Contact the administrator to get access."
            )
            return False
        return True

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await update.message.reply_text(
            "IPv666 Proxy Management Bot\n\n"
            "Commands:\n"
            "/create <count> <protocols> - Create proxies\n"
            "/list - List all proxies\n"
            "/delete <id> - Delete a proxy\n"
            "/stats - View statistics\n"
            "/help - Show help\n\n"
            "Or just chat naturally in Chinese/English and I'll understand!"
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        await update.message.reply_text(
            "IPv666 Help\n\n"
            "Just tell me what you want:\n"
            "- \"Create 5 proxies with VLESS and Shadowsocks\"\n"
            "- \"Show all my proxies\"\n"
            "- \"Delete proxy 3\"\n"
            "- \"Check proxy health\"\n"
            "- \"How many active proxies do I have?\"\n\n"
            "Supported protocols: VLESS, VMess, Trojan, Shadowsocks, SOCKS5, HTTP"
        )

    async def _cmd_create(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /create <count> [protocols...]\nExample: /create 5 vless ss")
            return

        try:
            count = int(args[0])
        except ValueError:
            count = 1

        protocols = args[1:] if len(args) > 1 else ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]
        protocols = self._normalize_protocols(protocols)

        msg = await update.message.reply_text(f"Creating {count} proxies with {', '.join(protocols)}...")

        created_count, results = await self.orchestrator.create_proxies(count, protocols, purpose="Command")

        if created_count == 0:
            await msg.edit_text("Failed to create any proxies. Check server logs.")
            return

        response_lines = [f"Created {created_count} proxies:"]
        for r in results[:10]:
            response_lines.append(f"\nProxy #{r['id']}: {r['ipv6_addr']}")
            for proto, link in r.get("share_links", {}).items():
                if len(link) > 80:
                    link = link[:77] + "..."
                response_lines.append(f"  {proto}: {link}")

        if created_count > 10:
            response_lines.append(f"\n... and {created_count - 10} more. Use /list to see all.")

        await msg.edit_text("\n".join(response_lines))

    async def _cmd_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        proxies = await self.orchestrator.list_proxies()
        if not proxies:
            await update.message.reply_text("No proxies found.")
            return

        active = sum(1 for p in proxies if p["status"] == "active")
        error = sum(1 for p in proxies if p["status"] == "error")

        lines = [f"Proxies: {len(proxies)} total ({active} active, {error} error)\n"]

        for p in proxies[:20]:
            proto_str = ",".join(p["protocols"][:3])
            if len(p["protocols"]) > 3:
                proto_str += f"+{len(p['protocols'])-3}"
            lines.append(f"#{p['id']} [{p['status']}] {p['ipv6_addr']} :{p['base_port']} ({proto_str})")

        if len(proxies) > 20:
            lines.append(f"\n... and {len(proxies) - 20} more.")

        lines.append(f"\n\nUse /list <id> to view share links for a specific proxy.")

        await update.message.reply_text("\n".join(lines))

    async def _cmd_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /delete <id>\nExample: /delete 3")
            return

        try:
            proxy_id = int(args[0])
        except ValueError:
            await update.message.reply_text("Invalid ID. Use a number.")
            return

        msg = await update.message.reply_text(f"Deleting proxy #{proxy_id}...")
        success = await self.orchestrator.delete_proxy(proxy_id=proxy_id)

        if success:
            await msg.edit_text(f"Proxy #{proxy_id} deleted.")
        else:
            await msg.edit_text(f"Failed to delete proxy #{proxy_id}. Check server logs.")

    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        stats = await self.orchestrator.get_stats()
        await update.message.reply_text(
            f"IPv666 Statistics\n\n"
            f"Total proxies: {stats.get('total', 0)}\n"
            f"  Active: {stats.get('active', 0)}\n"
            f"  Error:  {stats.get('error', 0)}\n"
            f"  Creating: {stats.get('creating', 0)}\n"
            f"Allocated IPv6: {stats.get('allocated_ips', 0)}"
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        message = update.message.text
        logger.info(f"Received message from {update.effective_user.id}: {message}")

        status_msg = await update.message.reply_text("Processing...")

        intent = await self.intent_parser.parse(message)

        try:
            if intent["action"] == "create":
                response = await self._handle_create_intent(intent)
            elif intent["action"] == "delete":
                response = await self._handle_delete_intent(intent)
            elif intent["action"] == "list":
                response = await self._handle_list_intent()
            elif intent["action"] == "status":
                response = await self._handle_status_intent()
            elif intent["action"] == "help":
                response = await self._handle_help_intent()
            else:
                response = "I didn't understand that. Try:\n- Create proxies\n- List proxies\n- Delete proxy\n- Check status"

            await status_msg.edit_text(response)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await status_msg.edit_text(f"Error processing request: {str(e)[:200]}")

    async def _handle_create_intent(self, intent: dict) -> str:
        count = intent.get("count", 1)
        protocols = intent.get("protocols", ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"])
        purpose = intent.get("purpose", "")

        created_count, results = await self.orchestrator.create_proxies(count, protocols, purpose)

        if created_count == 0:
            return "Failed to create proxies. The server may be out of IPv6 addresses or ports."

        lines = [f"Created {created_count} proxy(ies):\n"]
        for r in results:
            lines.append(f"\nProxy #{r['id']}: {r['ipv6_addr']} [{r['status']}]")
            for proto, link in r.get("share_links", {}).items():
                if len(link) > 80:
                    link = link[:77] + "..."
                lines.append(f"  {proto}: `{link}`")

        if len(results) == count:
            lines.append(f"\nAll {count} proxies created successfully.")
        else:
            lines.append(f"\nOnly {len(results)} of {count} proxies were created.")

        return "\n".join(lines)

    async def _handle_delete_intent(self, intent: dict) -> str:
        proxy_id = intent.get("target_id")
        ipv6_addr = intent.get("target_ip")

        if not proxy_id and not ipv6_addr:
            return "Please specify a proxy ID or IPv6 address to delete."

        success = await self.orchestrator.delete_proxy(proxy_id=proxy_id, ipv6_addr=ipv6_addr)

        if success:
            target = f"#{proxy_id}" if proxy_id else ipv6_addr
            return f"Proxy {target} deleted."
        else:
            return "Failed to delete proxy. It may not exist."

    async def _handle_list_intent(self) -> str:
        proxies = await self.orchestrator.list_proxies()
        if not proxies:
            return "No proxies found. Create some with: create 5 proxies"

        active = sum(1 for p in proxies if p["status"] == "active")
        error = sum(1 for p in proxies if p["status"] == "error")

        lines = [f"Your proxies: {len(proxies)} total ({active} active, {error} error)\n"]

        for p in proxies[:15]:
            proto_str = ",".join(p["protocols"][:3])
            if len(p["protocols"]) > 3:
                proto_str += f"+{len(p['protocols']) - 3}"
            lines.append(f"#{p['id']} [{p['status']}] {p['ipv6_addr']} ({proto_str})")

        if len(proxies) > 15:
            lines.append(f"\n... and {len(proxies) - 15} more.")

        return "\n".join(lines)

    async def _handle_status_intent(self) -> str:
        stats = await self.orchestrator.get_stats()
        result = await self.orchestrator.health_check_all()
        return (
            f"Health Check Results\n\n"
            f"Total proxies: {result['checked']}\n"
            f"  Healthy: {result['healthy']}\n"
            f"  Unhealthy: {result['unhealthy']}\n\n"
            f"Overall: Active={stats.get('active',0)}, Error={stats.get('error',0)}"
        )

    async def _handle_help_intent(self) -> str:
        return (
            "You can tell me things like:\n\n"
            "\"Create 5 proxies with VLESS and Shadowsocks\"\n"
            "\"Show all my proxies\"\n"
            "\"Delete proxy #3\"\n"
            "\"Check if proxies are working\"\n"
            "\"How many proxies do I have?\"\n"
            "\"Create 10 SOCKS5 proxies for web scraping\"\n\n"
            "Commands: /create /list /delete /stats /help"
        )

    def _normalize_protocols(self, raw: list[str]) -> list[str]:
        proto_map = {
            "vless": "vless",
            "vmess": "vmess",
            "trojan": "trojan",
            "ss": "shadowsocks",
            "shadowsocks": "shadowsocks",
            "socks5": "socks5",
            "socks": "socks5",
            "http": "http",
            "https": "http",
        }
        normalized = []
        seen = set()
        for p in raw:
            p_clean = p.lower().strip().rstrip("s")
            mapped = proto_map.get(p_clean)
            if mapped and mapped not in seen:
                normalized.append(mapped)
                seen.add(mapped)
        return normalized if normalized else ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Telegram bot error: {context.error}")
        if update and hasattr(update, "message") and update.message:
            try:
                await update.message.reply_text("An internal error occurred. Please try again.")
            except Exception:
                pass

    async def run(self):
        if not self.app:
            self.build_app()
        logger.info("Starting Telegram bot...")
        await self.app.run_polling(allowed_updates=Update.ALL_TYPES)

    async def stop(self):
        if self.app:
            await self.app.stop()
            await self.app.shutdown()
