import os
import subprocess

from src.utils.logger import logger


def apply_hardening():
    _disable_ipv6_privacy_extensions()
    _set_kernel_parameters()
    _restrict_permissions()
    logger.info("Security hardening applied.")


def _disable_ipv6_privacy_extensions():
    interface = os.environ.get("VPS_IPV6_INTERFACE", "eth0")
    try:
        subprocess.run(
            ["sysctl", "-w", f"net.ipv6.conf.{interface}.use_tempaddr=0"],
            capture_output=True, timeout=5
        )
        subprocess.run(
            ["sysctl", "-w", f"net.ipv6.conf.{interface}.autoconf=0"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass


def _set_kernel_parameters():
    params = {
        "net.ipv6.conf.all.forwarding": "1",
        "net.ipv6.conf.all.accept_redirects": "0",
        "net.ipv6.conf.all.accept_source_route": "0",
        "net.ipv4.conf.all.rp_filter": "1",
        "net.ipv4.tcp_syncookies": "1",
    }
    for key, value in params.items():
        try:
            subprocess.run(["sysctl", "-w", f"{key}={value}"], capture_output=True, timeout=5)
        except Exception:
            pass


def _restrict_permissions():
    paths = ["/app/data", "/app/certs", "/app/xray_configs"]
    for p in paths:
        try:
            os.chmod(p, 0o750)
        except Exception:
            pass
