import os

from src.db.models import Proxy
from src.utils.logger import logger

CERT_DIR = "/app/certs"


class TlsManager:
    def __init__(self, domain: str = "", email: str = "admin@example.com"):
        self.domain = domain
        self.email = email
        self.enabled = bool(domain)

    def get_cert_paths(self) -> tuple[str, str]:
        cert_path = os.path.join(CERT_DIR, "cert.pem")
        key_path = os.path.join(CERT_DIR, "key.pem")
        return cert_path, key_path

    def is_ready(self) -> bool:
        cert_path, key_path = self.get_cert_paths()
        return os.path.exists(cert_path) and os.path.exists(key_path)

    def setup_for_proxy(self, proxy: Proxy) -> bool:
        if not self.enabled:
            proxy.tls_enabled = False
            return False

        if self.is_ready():
            proxy.tls_enabled = True
            proxy.tls_domain = self.domain
            logger.info(f"TLS enabled for proxy {proxy.ipv6_addr} with domain {self.domain}")
            return True

        proxy.tls_enabled = False
        logger.warning(f"TLS not ready for proxy {proxy.ipv6_addr}")
        return False
