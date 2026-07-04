import asyncio
import subprocess

from src.utils.logger import logger


class FirewallManager:
    def __init__(self, interface: str = "eth0"):
        self.interface = interface
        self._fw_type = self._detect_firewall_type()

    def _detect_firewall_type(self) -> str:
        try:
            subprocess.run(["iptables", "--version"], capture_output=True, timeout=5)
            return "iptables"
        except Exception:
            pass
        try:
            subprocess.run(["nft", "--version"], capture_output=True, timeout=5)
            return "nftables"
        except Exception:
            pass
        return "none"

    async def open_port(self, port: int, protocol: str = "tcp"):
        if self._fw_type == "iptables":
            await self._iptables_open(port, protocol)
        elif self._fw_type == "nftables":
            await self._nftables_open(port, protocol)

    async def close_port(self, port: int, protocol: str = "tcp"):
        if self._fw_type == "iptables":
            await self._iptables_close(port, protocol)
        elif self._fw_type == "nftables":
            await self._nftables_close(port, protocol)

    async def open_port_range(self, start: int, end: int, protocol: str = "tcp"):
        if self._fw_type == "iptables":
            await self._iptables_open_range(start, end, protocol)
        elif self._fw_type == "nftables":
            await self._nftables_open_range(start, end, protocol)

    async def _iptables_open(self, port: int, protocol: str = "tcp"):
        for cmd in ["iptables", "ip6tables"]:
            try:
                result = subprocess.run(
                    [cmd, "-C", "INPUT", "-p", protocol, "--dport", str(port), "-j", "ACCEPT"],
                    capture_output=True, timeout=5
                )
                if result.returncode != 0:
                    subprocess.run(
                        [cmd, "-A", "INPUT", "-p", protocol, "--dport", str(port), "-j", "ACCEPT"],
                        capture_output=True, timeout=5
                    )
            except Exception as e:
                logger.error(f"Firewall ({cmd}) open port {port} failed: {e}")

    async def _iptables_close(self, port: int, protocol: str = "tcp"):
        for cmd in ["iptables", "ip6tables"]:
            try:
                subprocess.run(
                    [cmd, "-D", "INPUT", "-p", protocol, "--dport", str(port), "-j", "ACCEPT"],
                    capture_output=True, timeout=5
                )
            except Exception:
                pass

    async def _iptables_open_range(self, start: int, end: int, protocol: str = "tcp"):
        for cmd in ["iptables", "ip6tables"]:
            try:
                result = subprocess.run(
                    [cmd, "-C", "INPUT", "-p", protocol, "--dport", f"{start}:{end}", "-j", "ACCEPT"],
                    capture_output=True, timeout=5
                )
                if result.returncode != 0:
                    subprocess.run(
                        [cmd, "-A", "INPUT", "-p", protocol, "--dport", f"{start}:{end}", "-j", "ACCEPT"],
                        capture_output=True, timeout=5
                    )
            except Exception as e:
                logger.error(f"Firewall ({cmd}) open range {start}-{end} failed: {e}")

    async def _nftables_open(self, port: int, protocol: str = "tcp"):
        try:
            subprocess.run(
                ["nft", "add", "rule", "inet", "ipv666", "input",
                 protocol, "dport", str(port), "accept", "comment", f"\"ipv666-{port}\""],
                capture_output=True, timeout=5
            )
        except Exception as e:
            logger.error(f"nftables open port {port} failed: {e}")

    async def _nftables_close(self, port: int, protocol: str = "tcp"):
        try:
            subprocess.run(
                ["nft", "delete", "rule", "inet", "ipv666", "input",
                 "handle", "0"],
                capture_output=True, timeout=5
            )
        except Exception:
            pass

    async def _nftables_open_range(self, start: int, end: int, protocol: str = "tcp"):
        for port in range(start, end + 1):
            await self._nftables_open(port, protocol)
