import json

from src.db.models import Proxy


def generate_vless_inbound(proxy: Proxy, port: int) -> dict:
    cfg = {
        "listen": proxy.ipv6_addr,
        "port": port,
        "protocol": "vless",
        "settings": {
            "clients": [
                {
                    "id": proxy.cred_uuids.get("vless", ""),
                    "level": 0,
                    "email": f"vless-{proxy.id}",
                }
            ],
            "decryption": "none",
        },
        "streamSettings": {
            "network": "tcp",
            "security": "none",
        },
        "tag": f"inbound-vless-{proxy.id}",
    }
    if proxy.tls_enabled and proxy.tls_domain:
        cfg["streamSettings"]["security"] = "tls"
        cfg["streamSettings"]["tlsSettings"] = {
            "certificates": [
                {
                    "certificateFile": "/app/certs/cert.pem",
                    "keyFile": "/app/certs/key.pem",
                }
            ],
            "serverName": proxy.tls_domain,
        }
    return cfg


def generate_vmess_inbound(proxy: Proxy, port: int) -> dict:
    cfg = {
        "listen": proxy.ipv6_addr,
        "port": port,
        "protocol": "vmess",
        "settings": {
            "clients": [
                {
                    "id": proxy.cred_uuids.get("vmess", ""),
                    "level": 0,
                    "email": f"vmess-{proxy.id}",
                    "alterId": 0,
                    "security": "auto",
                }
            ],
        },
        "streamSettings": {
            "network": "tcp",
            "security": "none",
        },
        "tag": f"inbound-vmess-{proxy.id}",
    }
    if proxy.tls_enabled and proxy.tls_domain:
        cfg["streamSettings"]["security"] = "tls"
        cfg["streamSettings"]["tlsSettings"] = {
            "certificates": [
                {
                    "certificateFile": "/app/certs/cert.pem",
                    "keyFile": "/app/certs/key.pem",
                }
            ],
            "serverName": proxy.tls_domain,
        }
    return cfg


def generate_trojan_inbound(proxy: Proxy, port: int) -> dict:
    cfg = {
        "listen": proxy.ipv6_addr,
        "port": port,
        "protocol": "trojan",
        "settings": {
            "clients": [
                {
                    "password": proxy.cred_passwords.get("trojan", ""),
                    "level": 0,
                    "email": f"trojan-{proxy.id}",
                }
            ],
        },
        "streamSettings": {
            "network": "tcp",
            "security": "tls",
            "tlsSettings": {
                "certificates": [
                    {
                        "certificateFile": "/app/certs/cert.pem",
                        "keyFile": "/app/certs/key.pem",
                    }
                ],
                "serverName": proxy.tls_domain or proxy.ipv6_addr,
            },
        },
        "tag": f"inbound-trojan-{proxy.id}",
    }
    return cfg


def generate_shadowsocks_inbound(proxy: Proxy, port: int) -> dict:
    return {
        "listen": proxy.ipv6_addr,
        "port": port,
        "protocol": "shadowsocks",
        "settings": {
            "method": "aes-256-gcm",
            "password": proxy.cred_passwords.get("shadowsocks", ""),
            "level": 0,
            "email": f"ss-{proxy.id}",
            "network": "tcp,udp",
        },
        "tag": f"inbound-ss-{proxy.id}",
    }


def generate_socks5_inbound(proxy: Proxy, port: int) -> dict:
    return {
        "listen": proxy.ipv6_addr,
        "port": port,
        "protocol": "socks",
        "settings": {
            "auth": "password",
            "accounts": [
                {
                    "user": "proxy",
                    "pass": proxy.cred_passwords.get("socks5", ""),
                }
            ],
            "udp": True,
            "level": 0,
        },
        "tag": f"inbound-socks5-{proxy.id}",
    }


def generate_http_inbound(proxy: Proxy, port: int) -> dict:
    return {
        "listen": proxy.ipv6_addr,
        "port": port,
        "protocol": "http",
        "settings": {
            "accounts": [
                {
                    "user": "proxy",
                    "pass": proxy.cred_passwords.get("http", ""),
                }
            ],
            "allowTransparent": False,
            "userLevel": 0,
        },
        "tag": f"inbound-http-{proxy.id}",
    }


PROTOCOL_GENERATORS = {
    "vless": generate_vless_inbound,
    "vmess": generate_vmess_inbound,
    "trojan": generate_trojan_inbound,
    "shadowsocks": generate_shadowsocks_inbound,
    "socks5": generate_socks5_inbound,
    "http": generate_http_inbound,
}


def generate_inbound_for_proxy(proxy: Proxy) -> list[dict]:
    inbounds = []
    ports = _get_proxy_ports(proxy)
    for proto in proxy.protocols:
        p = proto.lower()
        if p in PROTOCOL_GENERATORS and p in ports:
            try:
                inbound = PROTOCOL_GENERATORS[p](proxy, ports[p])
                inbounds.append(inbound)
            except Exception as e:
                from src.utils.logger import logger
                logger.error(f"Failed to generate {p} inbound for {proxy.ipv6_addr}: {e}")
    return inbounds


def _get_proxy_ports(proxy: Proxy) -> dict[str, int]:
    ports = {}
    for proto in proxy.protocols:
        p = proto.lower()
        protocol_index = _PROTOCOL_ORDER.index(p) if p in _PROTOCOL_ORDER else 0
        ports[p] = proxy.base_port + protocol_index
    return ports


_PROTOCOL_ORDER = ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"]
