import os
import re
import subprocess

from src.utils.logger import logger


class SubnetDetector:
    def __init__(self, interface: str = "eth0"):
        self.interface = interface
        self.primary_addr: str = ""
        self.prefix_len: int = 64
        self.subnet_base: str = ""
        self.gateway: str = ""

    def detect(self) -> dict:
        self._detect_primary_address()
        self._detect_prefix()
        self._detect_gateway()
        self._calculate_subnet_base()

        return {
            "interface": self.interface,
            "primary_addr": self.primary_addr,
            "prefix_len": self.prefix_len,
            "subnet_base": self.subnet_base,
            "gateway": self.gateway,
            "usable_range_start": f"{self.subnet_base}::2",
            "usable_range_end": self._calculate_range_end(),
        }

    def _detect_primary_address(self):
        try:
            result = subprocess.run(
                ["ip", "-6", "addr", "show", "dev", self.interface, "scope", "global"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split("\n"):
                match = re.search(r"inet6\s+([0-9a-f:]+)/(\d+)", line)
                if match:
                    self.primary_addr = match.group(1)
                    self.prefix_len = int(match.group(2))
                    logger.info(f"Detected primary IPv6: {self.primary_addr}/{self.prefix_len}")
                    return
        except Exception as e:
            logger.error(f"Failed to detect primary IPv6: {e}")

        if not self.primary_addr:
            self.primary_addr = self._fallback_detect()
            logger.warning(f"Using fallback primary IPv6: {self.primary_addr}")

    def _fallback_detect(self) -> str:
        try:
            result = subprocess.run(
                ["ip", "-6", "addr", "show", "scope", "global"],
                capture_output=True, text=True, timeout=10
            )
            match = re.search(r"inet6\s+([0-9a-f:]+)/(\d+)", result.stdout)
            if match:
                return match.group(1)
        except Exception:
            pass
        return "::1"

    def _detect_prefix(self):
        try:
            result = subprocess.run(
                ["ip", "-6", "route", "show", "dev", self.interface],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.split("\n"):
                match = re.search(r"([0-9a-f:]+)/(\d+)", line)
                if match and int(match.group(2)) <= 64:
                    self.prefix_len = int(match.group(2))
                    logger.info(f"Detected prefix length: /{self.prefix_len}")
                    return
        except Exception as e:
            logger.error(f"Failed to detect prefix: {e}")

    def _detect_gateway(self):
        try:
            result = subprocess.run(
                ["ip", "-6", "route", "show", "default"],
                capture_output=True, text=True, timeout=10
            )
            match = re.search(r"via\s+([0-9a-f:]+)", result.stdout)
            if match:
                self.gateway = match.group(1)
                logger.info(f"Detected IPv6 gateway: {self.gateway}")
        except Exception as e:
            logger.error(f"Failed to detect gateway: {e}")

    def _calculate_subnet_base(self):
        if not self.primary_addr:
            return
        parts = self.primary_addr.split(":")
        if self.prefix_len == 64:
            self.subnet_base = ":".join(parts[:4])
        elif self.prefix_len == 48:
            self.subnet_base = ":".join(parts[:3])
        else:
            groups = self.prefix_len // 16
            self.subnet_base = ":".join(parts[:groups])
        logger.info(f"Subnet base: {self.subnet_base}::/{self.prefix_len}")

    def _calculate_range_end(self) -> str:
        if self.prefix_len == 64:
            return f"{self.subnet_base}:ffff:ffff:ffff:ffff"
        elif self.prefix_len == 48:
            return f"{self.subnet_base}:ffff:ffff:ffff:ffff:ffff"
        return f"{self.subnet_base}::ffff"
