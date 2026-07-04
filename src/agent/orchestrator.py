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
        if not protocols:
            logger.warning("create_proxies called with empty protocols")
            return 0, []

        max_proxies = self.config.get("agent", {}).get("max_proxies", 5000)
        current = await self._count_proxies()
        if current + count > max_proxies:
            count = max(1, max_proxies - current)
            logger.warning(f"Proxy limit near, reducing to {count}")

        available = await self._get_next_available_port()
        if available is None:
            return 0, []

        addresses = await self.address_manager.allocate_addresses(count)
        if len(addresses) < count:
            return 0, []

        # Phase 1: Create and save all proxies to DB (no Xray reload yet)
        pending_proxies = []
        for i, addr in enumerate(addresses):
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
                    await self.firewall.open_port(base_port + j)

                proxy_id = await self._save_proxy(proxy)
                proxy.id = proxy_id
                pending_proxies.append(proxy)
            except Exception as e:
                logger.error(f"Failed to create proxy for {addr}: {e}")
                await log_operation("create_proxy", target_ip=addr, result="failed", detail=str(e))

        if not pending_proxies:
            return 0, []

        # Phase 2: Add all proxies to Xray and reload once
        await self.xray_manager.add_proxies_batch(pending_proxies)
        await asyncio.sleep(3.0)  # Let Xray fully start

        # Phase 3: Verify each proxy, collecting failures for batch rollback
        results = []
        failed_proxy_ids = []

        # Don't generate the Xray config until after all rollbacks
        # Actually, need to add all verified proxies first
        for proxy in pending_proxies:
            try:
                if self.config.get("agent", {}).get("verify_new_proxy", True):
                    verified = False
                    for retry in range(3):
                        if retry > 0:
                            await asyncio.sleep(2.0)
                        verified = await self.verifier.verify(proxy, timeout=5)
                        if verified:
                            break
                    if verified:
                        proxy.status = "active"
                    else:
                        proxy.status = "error"
                        proxy.verify_count = 1
                        logger.warning(f"Proxy {proxy.id} ({proxy.ipv6_addr}) verification failed")
                        failed_proxy_ids.append(proxy.id)
                        continue
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
                    "cred_uuids": proxy.cred_uuids,
                    "cred_passwords": proxy.cred_passwords,
                })

                await log_operation(
                    "create_proxy", target_id=proxy.id, target_ip=proxy.ipv6_addr,
                    result="success", detail=f"protocols={','.join(protocols)}"
                )
                logger.info(f"Created proxy {proxy.id}: {proxy.ipv6_addr} ports {proxy.base_port}-{proxy.base_port+len(protocols)-1}")

            except Exception as e:
                logger.error(f"Failed to create proxy for {proxy.ipv6_addr}: {e}")
                await log_operation("create_proxy", target_ip=proxy.ipv6_addr, result="failed", detail=str(e))
                failed_proxy_ids.append(proxy.id)

        # Phase 4: Batch rollback all failed proxies at once, then single Xray reload
        if failed_proxy_ids:
            for pid in failed_proxy_ids:
                await self._delete_proxy_db_only(pid)
            # Reload Xray once with only successful proxies
            await self.xray_manager.reload_from_db()

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
                await db.execute("UPDATE ipv6_pool SET proxy_id=NULL, allocated_at=NULL WHERE proxy_id=?", (proxy.id,))
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
                    "cred_uuids": json.loads(d["cred_uuids"]) if d["cred_uuids"] else {},
                    "cred_passwords": json.loads(d["cred_passwords"]) if d["cred_passwords"] else {},
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
                cursor_proto = await db.execute(
                    "SELECT protocols FROM proxies WHERE base_port = ? AND status != 'deleted'",
                    (row[0],)
                )
                proto_row = await cursor_proto.fetchone()
                if proto_row:
                    protocol_count = len(json.loads(proto_row[0]))
                    max_port = row[0] + protocol_count
                else:
                    max_port = row[0] + 1
            else:
                max_port = self.base_port

            cursor2 = await db.execute(
                "SELECT base_port FROM proxies ORDER BY base_port"
            )
            used = {row[0] for row in await cursor2.fetchall()}

            port = max_port
            while port < 65535:
                if port not in used:
                    return port
                port += 1
            # wrap around: scan from base_port upward for gaps
            port = self.base_port
            while port < max_port:
                if port not in used:
                    return port
                port += 1
            return None
        finally:
            await db.close()

    async def _count_proxies(self) -> int:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT COUNT(*) FROM proxies WHERE status != 'deleted'")
            row = await cursor.fetchone()
            return row[0] if row else 0
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

    async def _delete_proxy_db_only(self, proxy_id: int):
        """Delete proxy from DB without triggering Xray reload (used in batch rollback)."""
        try:
            db = await get_db()
            try:
                await db.execute("UPDATE proxies SET status='deleted', updated_at=? WHERE id=?",
                                 (datetime.now().isoformat(), proxy_id))
                await db.execute("DELETE FROM port_allocations WHERE proxy_id=?", (proxy_id,))
                await db.execute("UPDATE ipv6_pool SET proxy_id=NULL, allocated_at=NULL WHERE proxy_id=?", (proxy_id,))
                await db.commit()
            finally:
                await db.close()
        except Exception as e:
            logger.error(f"DB-only delete failed for proxy {proxy_id}: {e}")

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
                if is_ok:
                    await db.execute(
                        "UPDATE proxies SET status='active', verify_count=0, last_check=? WHERE id=?",
                        (datetime.now().isoformat(), proxy_id)
                    )
                else:
                    await db.execute(
                        "UPDATE proxies SET verify_count=verify_count+1, last_check=? WHERE id=?",
                        (datetime.now().isoformat(), proxy_id)
                    )
            await db.commit()

            return {"checked": len(results), "healthy": healthy, "unhealthy": unhealthy}
        finally:
            await db.close()

    async def shutdown(self):
        logger.info("Shutting down orchestrator...")
