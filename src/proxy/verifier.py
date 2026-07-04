import asyncio
import socket

from src.db.models import Proxy
from src.utils.logger import logger


class ProxyVerifier:
    async def verify(self, proxy: Proxy, timeout: int = 5) -> bool:
        if not proxy.protocols:
            return False

        first_proto = proxy.protocols[0].lower()
        port = proxy.base_port

        try:
            if "shadowsocks" in [p.lower() for p in proxy.protocols]:
                for i, p in enumerate(proxy.protocols):
                    if p.lower() == "shadowsocks":
                        port = proxy.base_port + i
                        break

            connected = await self._check_tcp_connect(proxy.ipv6_addr, port, timeout)
            if connected:
                logger.info(f"Proxy verified: {proxy.ipv6_addr}:{port}")
                return True
            else:
                logger.warning(f"Proxy verification failed: {proxy.ipv6_addr}:{port}")
                return False
        except Exception as e:
            logger.error(f"Proxy verification error for {proxy.ipv6_addr}: {e}")
            return False

    async def _check_tcp_connect(self, host: str, port: int, timeout: int = 5) -> bool:
        try:
            addrinfo = await asyncio.get_event_loop().getaddrinfo(
                host, port, family=socket.AF_INET6, type=socket.SOCK_STREAM
            )
            if not addrinfo:
                return False

            family, socktype, proto, canonname, sockaddr = addrinfo[0]
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)

            result = await asyncio.get_event_loop().sock_connect(sock, sockaddr)
            sock.close()
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False
        except Exception as e:
            logger.debug(f"TCP connect check failed: {e}")
            return False

    async def verify_multiple(self, proxies: list[Proxy], timeout: int = 5) -> dict[int, bool]:
        results = {}
        tasks = []
        for proxy in proxies:
            task = asyncio.create_task(self._verify_with_result(proxy, timeout))
            tasks.append((proxy.id, task))

        for proxy_id, task in tasks:
            try:
                results[proxy_id] = await task
            except Exception:
                results[proxy_id] = False

        return results

    async def _verify_with_result(self, proxy: Proxy, timeout: int) -> bool:
        return await self.verify(proxy, timeout)
