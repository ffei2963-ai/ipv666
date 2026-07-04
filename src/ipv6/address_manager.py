import asyncio
import os
import re
import subprocess
from typing import Optional

from src.db.database import get_db, log_operation
from src.ipv6.subnet_detector import SubnetDetector
from src.utils.logger import logger

PERSIST_FILE = "/app/data/ipv6_persist"


class AddressManager:
    def __init__(self, interface: str = "eth0", prefix_len: int = 64, subnet_base: str = "",
                 start_offset: int = 2):
        self.interface = interface
        self.prefix_len = prefix_len
        self.subnet_base = subnet_base
        self.start_offset = start_offset
        self._detector = SubnetDetector(interface)

    async def initialize(self):
        info = self._detector.detect()
        self.prefix_len = info["prefix_len"]
        self.subnet_base = info["subnet_base"]
        logger.info(f"AddressManager initialized: {self.subnet_base}::/{self.prefix_len}")

    async def allocate_addresses(self, count: int) -> list[str]:
        allocated = []
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT address FROM ipv6_pool WHERE proxy_id IS NOT NULL"
            )
            existing = await cursor.fetchall()
            used_addresses = {row[0] for row in existing}

            offset = self.start_offset
            while len(allocated) < count and offset < 1000000:
                addr = f"{self.subnet_base}::{offset:x}"
                if addr not in used_addresses:
                    try:
                        await self._bind_address(addr)
                        await db.execute(
                            "INSERT OR REPLACE INTO ipv6_pool (address, proxy_id, allocated_at) VALUES (?, NULL, datetime('now'))",
                            (addr,)
                        )
                        allocated.append(addr)
                        self._persist(addr)
                        logger.info(f"Allocated and bound: {addr}")
                    except Exception as e:
                        logger.error(f"Failed to allocate {addr}: {e}")
                offset += 1

            await db.commit()
        finally:
            await db.close()

        await log_operation("allocate_addresses", detail=f"count={count}, allocated={len(allocated)}")
        return allocated

    async def _bind_address(self, address: str) -> bool:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["ip", "-6", "addr", "add", f"{address}/{self.prefix_len}", "dev", self.interface],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                if "File exists" in result.stderr:
                    logger.debug(f"Address already bound: {address}")
                    return True
                raise RuntimeError(f"ip addr add failed: {result.stderr.strip()}")
            return True
        except Exception as e:
            logger.error(f"Failed to bind {address}: {e}")
            raise

    async def release_address(self, address: str) -> bool:
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["ip", "-6", "addr", "del", f"{address}/{self.prefix_len}", "dev", self.interface],
                capture_output=True, text=True, timeout=10
            )
            self._unpersist(address)

            db = await get_db()
            try:
                await db.execute("UPDATE ipv6_pool SET proxy_id=NULL, allocated_at=NULL WHERE address = ?", (address,))
                await db.commit()
            finally:
                await db.close()

            logger.info(f"Released address: {address}")
            await log_operation("release_address", target_ip=address)
            return True
        except Exception as e:
            logger.error(f"Failed to release {address}: {e}")
            return False

    def _persist(self, address: str):
        try:
            with open(PERSIST_FILE, "a") as f:
                f.write(f"{address}\n")
        except Exception as e:
            logger.error(f"Failed to persist {address}: {e}")

    def _unpersist(self, address: str):
        try:
            if not os.path.exists(PERSIST_FILE):
                return
            with open(PERSIST_FILE, "r") as f:
                lines = f.readlines()
            seen = set()
            unique_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and stripped != address and stripped not in seen:
                    unique_lines.append(line)
                    seen.add(stripped)
            with open(PERSIST_FILE, "w") as f:
                f.writelines(unique_lines)
        except Exception as e:
            logger.error(f"Failed to unpersist {address}: {e}")

    async def get_allocated_count(self) -> int:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT COUNT(*) FROM ipv6_pool WHERE proxy_id IS NOT NULL")
            row = await cursor.fetchone()
            return row[0] if row else 0
        finally:
            await db.close()

    async def restore_persisted_addresses(self):
        if not os.path.exists(PERSIST_FILE):
            return
        with open(PERSIST_FILE, "r") as f:
            addresses = list(set(line.strip() for line in f if line.strip()))
        for addr in addresses:
            try:
                await self._bind_address(addr)
            except Exception:
                pass
        logger.info(f"Restored {len(addresses)} persisted addresses")
