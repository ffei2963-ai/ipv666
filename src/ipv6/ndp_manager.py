import asyncio
import subprocess
import os

from src.utils.logger import logger

NDPPD_CONFIG = "/etc/ndppd.conf"


class NdpManager:
    def __init__(self, interface: str = "eth0", subnet_base: str = "", prefix_len: int = 64):
        self.interface = interface
        self.subnet_base = subnet_base
        self.prefix_len = prefix_len
        self.enabled = False

    async def setup(self) -> bool:
        if not self.subnet_base:
            logger.warning("NDP: No subnet base configured, skipping NDP proxy setup")
            return False

        needs_ndp = await self._check_ndp_needed()
        if not needs_ndp:
            self.enabled = False
            return False

        self.enabled = True
        await self._write_config()
        await self._restart_ndppd()
        return True

    async def _check_ndp_needed(self) -> bool:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["cat", "/app/data/ipv6_env"],
                capture_output=True, text=True, timeout=5
            )
            if "NDP_PROXY_REQUIRED=true" in result.stdout:
                return True
            return False
        except Exception:
            return False

    async def _write_config(self):
        config = f"""route-ttl 30000
address-ttl 30000

proxy {self.interface} {{
    router yes
    timeout 500
    ttl 30000

    rule {self.subnet_base}::/{self.prefix_len} {{
        static
    }}
}}
"""
        await asyncio.to_thread(
            lambda: open(NDPPD_CONFIG, "w").write(config)
        )
        logger.info("NDP proxy config written")

    async def _restart_ndppd(self):
        try:
            subprocess.run(["killall", "ndppd"], capture_output=True, timeout=5)
            await asyncio.sleep(1)
        except Exception:
            pass

        try:
            subprocess.Popen(
                ["ndppd", "-d"],
                stdout=open("/var/log/ndppd.log", "a"),
                stderr=subprocess.STDOUT
            )
            await asyncio.sleep(1)
            logger.info("NDP proxy daemon started")
        except Exception as e:
            logger.error(f"Failed to start ndppd: {e}")

    async def shutdown(self):
        try:
            subprocess.run(["killall", "ndppd"], capture_output=True, timeout=5)
            logger.info("NDP proxy stopped")
        except Exception:
            pass
