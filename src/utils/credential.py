import uuid
import secrets
import string


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_ss_password() -> str:
    return secrets.token_hex(16)


def generate_proxy_credentials(protocols: list) -> tuple[dict, dict]:
    uuids = {}
    passwords = {}

    for proto in protocols:
        p = proto.lower()
        if p in ("vless", "vmess"):
            uuids[p] = generate_uuid()
        elif p == "trojan":
            passwords[p] = generate_password(24)
        elif p == "shadowsocks":
            passwords[p] = generate_ss_password()
        elif p in ("socks5", "http"):
            passwords[p] = generate_password(12)

    return uuids, passwords
