import base64
import json

from src.db.models import Proxy
from src.utils.logger import logger


def generate_vless_link(proxy: Proxy, port: int) -> str:
    uuid = proxy.cred_uuids.get("vless", "")
    host = f"[{proxy.ipv6_addr}]"
    params = {
        "type": "tcp",
        "security": "tls" if proxy.tls_enabled else "none",
        "encryption": "none",
    }
    if proxy.tls_enabled and proxy.tls_domain:
        params["sni"] = proxy.tls_domain
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    remark = f"IPv666-{proxy.id}"
    import urllib.parse
    remark_encoded = urllib.parse.quote(remark)
    return f"vless://{uuid}@{host}:{port}?{param_str}#{remark_encoded}"


def generate_vmess_link(proxy: Proxy, port: int) -> str:
    uuid = proxy.cred_uuids.get("vmess", "")
    host = proxy.ipv6_addr
    config = {
        "v": "2",
        "ps": f"IPv666-{proxy.id}",
        "add": host,
        "port": str(port),
        "id": uuid,
        "aid": "0",
        "scy": "auto",
        "net": "tcp",
        "type": "none",
        "host": "",
        "path": "",
        "tls": "tls" if proxy.tls_enabled else "none",
        "sni": proxy.tls_domain if proxy.tls_enabled else "",
        "alpn": "",
    }
    config_json = json.dumps(config)
    return "vmess://" + base64.b64encode(config_json.encode()).decode()


def generate_trojan_link(proxy: Proxy, port: int) -> str:
    password = proxy.cred_passwords.get("trojan", "")
    host = f"[{proxy.ipv6_addr}]"
    import urllib.parse
    remark = urllib.parse.quote(f"IPv666-{proxy.id}")
    params = ""
    if proxy.tls_enabled and proxy.tls_domain:
        params = f"?sni={proxy.tls_domain}"
    return f"trojan://{password}@{host}:{port}{params}#{remark}"


def generate_shadowsocks_link(proxy: Proxy, port: int) -> str:
    password = proxy.cred_passwords.get("shadowsocks", "")
    host = f"[{proxy.ipv6_addr}]"
    import urllib.parse
    remark = urllib.parse.quote(f"IPv666-{proxy.id}")
    method = "aes-256-gcm"
    userinfo = base64.b64encode(f"{method}:{password}".encode()).decode()
    return f"ss://{userinfo}@{host}:{port}#{remark}"


def generate_socks5_info(proxy: Proxy, port: int) -> str:
    return f"socks5://proxy:{proxy.cred_passwords.get('socks5', '')}@[{proxy.ipv6_addr}]:{port}"


def generate_http_info(proxy: Proxy, port: int) -> str:
    return f"http://proxy:{proxy.cred_passwords.get('http', '')}@[{proxy.ipv6_addr}]:{port}"


SHARE_LINK_GENERATORS = {
    "vless": generate_vless_link,
    "vmess": generate_vmess_link,
    "trojan": generate_trojan_link,
    "shadowsocks": generate_shadowsocks_link,
    "socks5": generate_socks5_info,
    "http": generate_http_info,
}


def generate_all_share_links(proxy: Proxy) -> dict[str, str]:
    links = {}
    port_offset = 0
    for proto in proxy.protocols:
        p = proto.lower()
        if p in SHARE_LINK_GENERATORS:
            actual_port = proxy.base_port + port_offset
            try:
                links[p] = SHARE_LINK_GENERATORS[p](proxy, actual_port)
            except Exception as e:
                logger.error(f"Failed to generate share link for {p}: {e}")
                links[p] = f"Error generating {p} link"
        port_offset += 1
    return links
