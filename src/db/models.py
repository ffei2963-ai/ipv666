import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Proxy:
    id: Optional[int] = None
    ipv6_addr: str = ""
    base_port: int = 0
    protocols: list = field(default_factory=lambda: ["vless", "vmess", "trojan", "shadowsocks", "socks5", "http"])
    status: str = "creating"
    cred_uuids: dict = field(default_factory=dict)
    cred_passwords: dict = field(default_factory=dict)
    tls_enabled: bool = False
    tls_domain: str = ""
    config_snapshot: str = ""
    share_links: dict = field(default_factory=dict)
    verify_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_check: Optional[str] = None

    def to_row(self) -> tuple:
        return (
            self.ipv6_addr,
            self.base_port,
            json.dumps(self.protocols),
            self.status,
            json.dumps(self.cred_uuids),
            json.dumps(self.cred_passwords),
            int(self.tls_enabled),
            self.tls_domain,
            self.config_snapshot,
            json.dumps(self.share_links),
            self.verify_count,
        )

    @classmethod
    def from_row(cls, row: tuple) -> "Proxy":
        return cls(
            id=row[0],
            ipv6_addr=row[1],
            base_port=row[2],
            protocols=json.loads(row[3]) if row[3] else [],
            status=row[4],
            cred_uuids=json.loads(row[5]) if row[5] else {},
            cred_passwords=json.loads(row[6]) if row[6] else {},
            tls_enabled=bool(row[7]),
            tls_domain=row[8] or "",
            config_snapshot=row[9] or "",
            share_links=json.loads(row[10]) if row[10] else {},
            verify_count=row[11],
            created_at=row[12],
            updated_at=row[13],
            last_check=row[14],
        )


@dataclass
class BotUser:
    telegram_id: str = ""
    username: str = ""
    role: str = "user"
    added_at: Optional[str] = None
