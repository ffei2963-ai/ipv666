import asyncio
import json
import os
import subprocess
from typing import Optional

from src.db.models import Proxy
from src.proxy.xray_templates import generate_inbound_for_proxy
from src.utils.logger import logger

XRAY_CONFIG_DIR = "/usr/local/etc/xray"
XRAY_CONFIG = os.path.join(XRAY_CONFIG_DIR, "config.json")
XRAY_BIN = "/usr/local/bin/xray"

BASE_CONFIG = {
    "log": {
        "loglevel": "warning",
        "access": "/var/log/xray/access.log",
        "error": "/var/log/xray/error.log",
    },
    "inbounds": [],
    "outbounds": [
        {
            "protocol": "freedom",
            "settings": {},
            "tag": "direct",
        },
        {
            "protocol": "blackhole",
            "settings": {},
            "tag": "blocked",
        },
    ],
    "routing": {
        "domainStrategy": "IPIfNonMatch",
        "rules": [
            {
                "type": "field",
                "ip": ["geoip:private"],
                "outboundTag": "blocked",
            }
        ],
    },
}


class XrayManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._all_proxies: list[Proxy] = []

    async def load_existing(self, proxies: list[Proxy]):
        self._all_proxies = proxies
        await self._regenerate_config()

    async def add_proxy(self, proxy: Proxy):
        async with self._lock:
            self._all_proxies.append(proxy)
            await self._regenerate_config()

    async def remove_proxy(self, proxy_id: int):
        async with self._lock:
            self._all_proxies = [p for p in self._all_proxies if p.id != proxy_id]
            await self._regenerate_config()

    async def update_proxy(self, proxy: Proxy):
        async with self._lock:
            for i, p in enumerate(self._all_proxies):
                if p.id == proxy.id:
                    self._all_proxies[i] = proxy
                    break
            await self._regenerate_config()

    async def _regenerate_config(self):
        config = json.loads(json.dumps(BASE_CONFIG))
        config["inbounds"] = []

        for proxy in self._all_proxies:
            if proxy.status not in ("creating", "active"):
                continue
            inbounds = generate_inbound_for_proxy(proxy)
            config["inbounds"].extend(inbounds)

        await self._write_config(config)
        await self._reload()

    async def _write_config(self, config: dict):
        os.makedirs(XRAY_CONFIG_DIR, exist_ok=True)
        await asyncio.to_thread(
            lambda: json.dumps(config, indent=2) and open(XRAY_CONFIG, "w").write(
                json.dumps(config, indent=2)
            )
        )
        logger.info(f"Xray config written with {len(config['inbounds'])} inbounds")

    async def _reload(self):
        try:
            await asyncio.to_thread(
                subprocess.run,
                [XRAY_BIN, "run", "-config", XRAY_CONFIG, "-test"],
                capture_output=True, text=True, timeout=15
            )

            pid = await self._get_pid()
            if pid:
                os.kill(pid, 1)
                await asyncio.sleep(1)
                logger.info("Xray reloaded (SIGHUP)")
            else:
                await self._start()
        except Exception as e:
            logger.error(f"Xray reload failed: {e}")
            await self._start()

    async def _start(self):
        await asyncio.to_thread(
            subprocess.Popen,
            [XRAY_BIN, "run", "-config", XRAY_CONFIG],
            stdout=open("/var/log/xray/xray.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        await asyncio.sleep(2)
        if await self._get_pid():
            logger.info("Xray started")
        else:
            logger.error("Xray failed to start")

    async def _get_pid(self) -> Optional[int]:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["pgrep", "-f", "xray run"],
                capture_output=True, text=True, timeout=5
            )
            pid = result.stdout.strip().split("\n")[0]
            return int(pid) if pid else None
        except Exception:
            return None

    async def restart(self):
        pid = await self._get_pid()
        if pid:
            try:
                os.kill(pid, 9)
            except Exception:
                pass
            await asyncio.sleep(1)
        await self._start()
