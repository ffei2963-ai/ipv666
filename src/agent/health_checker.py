import asyncio
import json
from datetime import datetime

from src.db.database import get_db, log_operation
from src.db.models import Proxy
from src.proxy.verifier import ProxyVerifier
from src.utils.logger import logger


class HealthChecker:
    def __init__(self, interval: int = 60, timeout: int = 10, max_failures: int = 3):
        self.interval = interval
        self.timeout = timeout
        self.max_failures = max_failures
        self.verifier = ProxyVerifier()
        self._running = False
        self._task: asyncio.Task = None
        self._on_restart_callback = None
        self._error_cooldowns: dict[int, float] = {}  # proxy_id -> next check timestamp

    def set_restart_callback(self, callback):
        self._on_restart_callback = callback

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Health checker started, interval={self.interval}s")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self._check_all()
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
            await asyncio.sleep(self.interval)

    async def _check_all(self):
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM proxies WHERE status IN ('active', 'error')"
            )
            rows = await cursor.fetchall()

            if not rows:
                return

            column_names = [desc[0] for desc in cursor.description]
            now_ts = time.time()
            proxies = []
            for row in rows:
                proxy_dict = {column_names[i]: row[i] for i in range(len(row))}
                proxy = Proxy(
                    id=proxy_dict["id"],
                    ipv6_addr=proxy_dict["ipv6_addr"],
                    base_port=proxy_dict["base_port"],
                    status=proxy_dict["status"],
                    verify_count=proxy_dict["verify_count"],
                    protocols=json.loads(proxy_dict["protocols"]) if proxy_dict["protocols"] else [],
                )
                if proxy.status == "active":
                    proxies.append(proxy)
                elif proxy.status == "error":
                    cooldown_until = self._error_cooldowns.get(proxy.id, 0)
                    if now_ts >= cooldown_until:
                        proxies.append(proxy)
                        self._error_cooldowns[proxy.id] = now_ts + self.interval * 3

            if not proxies:
                return

            logger.debug(f"Health checking {len(proxies)} proxies")
            results = await self.verifier.verify_multiple(proxies, self.timeout)

            for proxy in proxies:
                is_healthy = results.get(proxy.id, False)
                if is_healthy:
                    await db.execute(
                        "UPDATE proxies SET status='active', verify_count=0, last_check=? WHERE id=?",
                        (datetime.now().isoformat(), proxy.id)
                    )
                    self._error_cooldowns.pop(proxy.id, None)
                else:
                    new_count = proxy.verify_count + 1
                    if new_count >= self.max_failures:
                        if proxy.status != "error":
                            await db.execute(
                                "UPDATE proxies SET status='error', verify_count=?, last_check=? WHERE id=?",
                                (new_count, datetime.now().isoformat(), proxy.id)
                            )
                            logger.warning(f"Proxy {proxy.id} ({proxy.ipv6_addr}) marked as error after {new_count} failures")
                        else:
                            await db.execute(
                                "UPDATE proxies SET verify_count=?, last_check=? WHERE id=?",
                                (new_count, datetime.now().isoformat(), proxy.id)
                            )
                        await self._try_restart_proxy(proxy)
                    else:
                        await db.execute(
                            "UPDATE proxies SET verify_count=?, last_check=? WHERE id=?",
                            (new_count, datetime.now().isoformat(), proxy.id)
                        )
            await db.commit()
        finally:
            await db.close()

    async def _try_restart_proxy(self, proxy: Proxy):
        logger.info(f"Attempting auto-repair for proxy {proxy.id}")
        if self._on_restart_callback:
            try:
                await self._on_restart_callback(proxy)
            except Exception as e:
                logger.error(f"Auto-restart callback failed for proxy {proxy.id}: {e}")

    async def check_single(self, proxy: Proxy) -> bool:
        return await self.verifier.verify(proxy, self.timeout)


import time
