import asyncio
import json
from datetime import datetime
from typing import Optional

from src.db.database import get_db, log_operation
from src.db.models import Proxy
from src.ipv6.address_manager import AddressManager
from src.proxy.xray_manager import XrayManager
from src.proxy.tls_manager import TlsManager
from src.proxy.share_link import generate_all_share_links
from src.proxy.verifier import ProxyVerifier
from src.security.firewall import FirewallManager
from src.utils.credential import generate_proxy_credentials
from src.utils.logger import logger


class Orchestrator:
    def __init__(self, config: dict):
        self.config = config
        self.address_manager = AddressManager(
            interface=config.get("ipv6", {}).get("interface", "eth0"),
            prefix_len=config.get("ipv6", {}).get("subnet_prefix", 64),
            subnet_base=config.get("ipv6", {}).get("subnet_base", ""),
            start_offset=config.get("ipv6", {}).get("address_start_offset", 2),
        )
        self.xray_manager = XrayManager()
        self.tls_manager = TlsManager(
            domain=config.get("proxy", {}).get("tls", {}).get("domain", ""),
            email=config.get("proxy", {}).get("tls", {}).get("email", "admin@example.com"),
        )
        self.firewall = FirewallManager(
            interface=config.get("ipv6", {}).get("interface", "eth0"),
        )
        self.verifier = ProxyVerifier()
        self.base_port = config.get("proxy", {}).get("base_port", 10000)

    async def initialize(self):
        await self.address_manager.initialize()
        await self._load_existing_proxies()

    async def _load_existing_proxies(self):
        db = await get_db()
        try:
            cursor = await db.execute("SELECT * FROM proxies WHERE status != 'deleted'")
            rows = await cursor.fetchall()
            if rows:
                column_names = [desc[0] for desc in cursor.description]
                proxies = []
                for row in rows:
                    d = {column_names[i]: row[i] for i in range(len(row))}
                    proxy = Proxy(
                        id=d["id"],
                        ipv6_addr=d["ipv6_addr"],
                        base_port=d["base_port"],
                        protocols=json.loads(d["protocols"]) if d["protocols"] else [],
                        status=d["status"],
                        cred_uuids=json.loads(d["cred_uuids"]) if d["cred_uuids"] else {},
                        cred_passwords=json.loads(d["cred_passwords"]) if d["cred_passwords"] else {},
                        tls_enabled=bool(d["tls_enabled"]),
                        tls_domain=d["tls_domain"] or "",
                        share_links=json.loads(d["share_links"]) if d["share_links"] else {},
                        verify_count=d["verify_count"],
                    )
                    proxies.append(proxy)
                await self.xray_manager.load_existing(proxies)
                logger.info(f"Loaded {len(proxies)} existing proxies from database")
        finally:
            await db.close()

    async def create_proxies(self, count: int, protocols: list[str],
                              purpose: str = "") -> tuple[int, list[dict]]:
        if count < 1:
            return 0, []

        available = await self._get_next_available_port()
        if available is None:
            return 0, []

        results = []
        addresses = await self.address_manager.allocate_addresses(count)
        if len(addresses) < count:
            return len(results), results

        for i, addr in enumerate(addresses):
            proxy = None
            try:
                base_port = available + i * len(protocols)
                proxy = Proxy(
                    ipv6_addr=addr,
                    base_port=base_port,
                    protocols=list(protocols),
                    status="creating",
                )

                uuids, passwords = generate_proxy_credentials(protocols)
                proxy.cred_uuids = uuids
                proxy.cred_passwords = passwords

                self.tls_manager.setup_for_proxy(proxy)

                for j, proto in enumerate(protocols):
                    port = base_port + j
                    await self.firewall.open_port(port)

                proxy_id = await self._save_proxy(proxy)
                proxy.id = proxy_id

                await self.xray_manager.add_proxy(proxy)
                await asyncio.sleep(0.5)

                if self.config.get("agent", {}).get("verify_new_proxy", True):
                    verified = await self.verifier.verify(proxy, timeout=8)
                    if verified:
                        proxy.status = "active"
                    else:
                        proxy.status = "error"
                        proxy.verify_count = 1
                else:
                    proxy.status = "active"

                share_links = generate_all_share_links(proxy)
                proxy.share_links = share_links

                await self._update_proxy_status(proxy)

                results.append({
                    "id": proxy.id,
                    "ipv6_addr": proxy.ipv6_addr,
                    "base_port": proxy.base_port,
                    "protocols": proxy.protocols,
                    "status": proxy.status,
                    "share_links": share_links,
                })

                await log_operation(
                    "create_proxy", target_id=proxy.id, target_ip=addr,
                    result="success", detail=f"protocols={','.join(protocols)}"
                )

                logger.info(f"Created proxy {proxy.id}: {addr} ports {base_port}-{base_port+len(protocols)-1}")

            except Exception as e:
                logger.error(f"Failed to create proxy for {addr}: {e}")
                await log_operation("create_proxy", target_ip=addr, result="failed", detail=str(e))
                if proxy and proxy.id:
                    await self._delete_proxy_safe(proxy.id)

        return len(results), results

    async def delete_proxy(self, proxy_id: int = None, ipv6_addr: str = None) -> bool:
        proxy = None
        if proxy_id:
            proxy = await self._get_proxy_by_id(proxy_id)
        elif ipv6_addr:
            proxy = await self._get_proxy_by_ip(ipv6_addr)

        if not proxy:
            logger.warning(f"Proxy not found: id={proxy_id}, ip={ipv6_addr}")
            return False

        try:
            for i in range(len(proxy.protocols)):
                port = proxy.base_port + i
                await self.firewall.close_port(port)

            await self.address_manager.release_address(proxy.ipv6_addr)
            await self.xray_manager.remove_proxy(proxy.id)

            db = await get_db()
            try:
                await db.execute("UPDATE proxies SET status='deleted', updated_at=? WHERE id=?",
                                 (datetime.now().isoformat(), proxy.id))
                await db.execute("DELETE FROM port_allocations WHERE proxy_id=?", (proxy.id,))
                await db.execute("DELETE FROM ipv6_pool WHERE proxy_id=?", (proxy.id,))
                await db.commit()
            finally:
                await db.close()

            await log_operation("delete_proxy", target_id=proxy.id, target_ip=proxy.ipv6_addr, result="success")
            logger.info(f"Deleted proxy {proxy.id}: {proxy.ipv6_addr}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete proxy {proxy.id}: {e}")
            await log_operation("delete_proxy", target_id=proxy_id, target_ip=ipv6_addr, result="failed", detail=str(e))
            return False

    async def list_proxies(self, status_filter: str = None) -> list[dict]:
        db = await get_db()
        try:
            if status_filter:
                cursor = await db.execute(
                    "SELECT * FROM proxies WHERE status = ? ORDER BY id",
                    (status_filter,)
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM proxies WHERE status != 'deleted' ORDER BY id"
                )
            rows = await cursor.fetchall()
            if not rows:
                return []

            column_names = [desc[0] for desc in cursor.description]
            result = []
            for row in rows:
                d = {column_names[i]: row[i] for i in range(len(row))}
                result.append({
                    "id": d["id"],
                    "ipv6_addr": d["ipv6_addr"],
                    "base_port": d["base_port"],
                    "protocols": json.loads(d["protocols"]) if d["protocols"] else [],
                    "status": d["status"],
                    "share_links": json.loads(d["share_links"]) if d["share_links"] else {},
                    "created_at": d["created_at"],
                    "last_check": d["last_check"],
                })
            return result
        finally:
            await db.close()

    async def get_stats(self) -> dict:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT status, COUNT(*) as cnt FROM proxies GROUP BY status"
            )
            rows = await cursor.fetchall()
            stats = {"active": 0, "error": 0, "creating": 0, "deleted": 0, "total": 0}
            for row in rows:
                stats[row[0]] = row[1]
                stats["total"] += row[1]

            cursor2 = await db.execute("SELECT COUNT(*) FROM ipv6_pool WHERE proxy_id IS NOT NULL")
            row2 = await cursor2.fetchone()
            stats["allocated_ips"] = row2[0] if row2 else 0

            return stats
        finally:
            await db.close()

    async def _get_next_available_port(self) -> Optional[int]:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT MAX(base_port) FROM proxies WHERE status != 'deleted'"
            )
            row = await cursor.fetchone()
            if row and row[0]:
                max_port = row[0] + 6
            else:
                max_port = self.base_port

            cursor2 = await db.execute(
                "SELECT base_port FROM proxies WHERE status != 'deleted' ORDER BY base_port"
            )
            used = {row[0] for row in await cursor2.fetchall()}

            port = max_port
            while port < 65535:
                if port not in used:
                    return port
                port += 1
            return None
        finally:
            await db.close()

    async def _save_proxy(self, proxy: Proxy) -> int:
        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO proxies
                   (ipv6_addr, base_port, protocols, status, cred_uuids, cred_passwords,
                    tls_enabled, tls_domain)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (proxy.ipv6_addr, proxy.base_port, json.dumps(proxy.protocols), proxy.status,
                 json.dumps(proxy.cred_uuids), json.dumps(proxy.cred_passwords),
                 int(proxy.tls_enabled), proxy.tls_domain)
            )

            proxy_id = cursor.lastrowid
            await db.execute(
                "UPDATE ipv6_pool SET proxy_id = ? WHERE address = ?",
                (proxy_id, proxy.ipv6_addr)
            )
            await db.commit()
            return proxy_id
        finally:
            await db.close()

    async def _update_proxy_status(self, proxy: Proxy):
        db = await get_db()
        try:
            await db.execute(
                """UPDATE proxies SET status=?, share_links=?, verify_count=?,
                   config_snapshot=?, updated_at=? WHERE id=?""",
                (proxy.status, json.dumps(proxy.share_links), proxy.verify_count,
                 proxy.config_snapshot or "", datetime.now().isoformat(), proxy.id)
            )
            await db.commit()
        finally:
            await db.close()

    async def _get_proxy_by_id(self, proxy_id: int) -> Optional[Proxy]:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT * FROM proxies WHERE id=? AND status!='deleted'", (proxy_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            column_names = [desc[0] for desc in cursor.description]
            d = {column_names[i]: row[i] for i in range(len(row))}
            return Proxy(
                id=d["id"],
                ipv6_addr=d["ipv6_addr"],
                base_port=d["base_port"],
                protocols=json.loads(d["protocols"]) if d["protocols"] else [],
                status=d["status"],
                cred_uuids=json.loads(d["cred_uuids"]) if d["cred_uuids"] else {},
                cred_passwords=json.loads(d["cred_passwords"]) if d["cred_passwords"] else {},
                tls_enabled=bool(d["tls_enabled"]),
                tls_domain=d["tls_domain"] or "",
                share_links=json.loads(d["share_links"]) if d["share_links"] else {},
                verify_count=d["verify_count"],
            )
        finally:
            await db.close()

    async def _get_proxy_by_ip(self, ipv6_addr: str) -> Optional[Proxy]:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM proxies WHERE ipv6_addr=? AND status!='deleted'",
                (ipv6_addr,)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            column_names = [desc[0] for desc in cursor.description]
            d = {column_names[i]: row[i] for i in range(len(row))}
            return Proxy(
                id=d["id"],
                ipv6_addr=d["ipv6_addr"],
                base_port=d["base_port"],
                protocols=json.loads(d["protocols"]) if d["protocols"] else [],
                status=d["status"],
                cred_uuids=json.loads(d["cred_uuids"]) if d["cred_uuids"] else {},
                cred_passwords=json.loads(d["cred_passwords"]) if d["cred_passwords"] else {},
                tls_enabled=bool(d["tls_enabled"]),
                tls_domain=d["tls_domain"] or "",
                share_links=json.loads(d["share_links"]) if d["share_links"] else {},
                verify_count=d["verify_count"],
            )
        finally:
            await db.close()

    async def _delete_proxy_safe(self, proxy_id: int):
        try:
            await self.delete_proxy(proxy_id=proxy_id)
        except Exception as e:
            logger.error(f"Safe delete failed for proxy {proxy_id}: {e}")

    async def health_check_all(self) -> dict:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT * FROM proxies WHERE status != 'deleted'")
            rows = await cursor.fetchall()
            if not rows:
                return {"checked": 0, "healthy": 0, "unhealthy": 0}

            column_names = [desc[0] for desc in cursor.description]
            proxies = []
            for row in rows:
                d = {column_names[i]: row[i] for i in range(len(row))}
                proxy = Proxy(
                    id=d["id"],
                    ipv6_addr=d["ipv6_addr"],
                    base_port=d["base_port"],
                    protocols=json.loads(d["protocols"]) if d["protocols"] else [],
                    status=d["status"],
                    verify_count=d["verify_count"],
                )
                proxies.append(proxy)

            results = await self.verifier.verify_multiple(proxies)
            healthy = sum(1 for v in results.values() if v)
            unhealthy = len(results) - healthy

            for proxy_id, is_ok in results.items():
                await db.execute(
                    "UPDATE proxies SET status=?, verify_count=?, last_check=? WHERE id=?",
                    ("active" if is_ok else "error",
                     0 if is_ok else 1,
                     datetime.now().isoformat(),
                     proxy_id)
                )
            await db.commit()

            return {"checked": len(results), "healthy": healthy, "unhealthy": unhealthy}
        finally:
            await db.close()

    async def shutdown(self):
        logger.info("Shutting down orchestrator...")
