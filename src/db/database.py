import os
import aiosqlite

DB_DIR = os.environ.get("DB_DIR", "/app/data")
DB_PATH = os.path.join(DB_DIR, "ipv666.db")


async def get_db():
    db = await aiosqlite.connect(DB_PATH, timeout=30)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS proxies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ipv6_addr       TEXT NOT NULL UNIQUE,
                base_port       INTEGER NOT NULL UNIQUE,
                protocols       TEXT NOT NULL DEFAULT '["vless","vmess","trojan","shadowsocks","socks5","http"]',
                status          TEXT NOT NULL DEFAULT 'creating',
                cred_uuids      TEXT,
                cred_passwords  TEXT,
                tls_enabled     INTEGER DEFAULT 0,
                tls_domain      TEXT,
                config_snapshot TEXT,
                share_links     TEXT,
                verify_count    INTEGER DEFAULT 0,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_check      DATETIME
            );

            CREATE TABLE IF NOT EXISTS port_allocations (
                port        INTEGER PRIMARY KEY,
                proxy_id    INTEGER NOT NULL,
                protocol    TEXT NOT NULL,
                FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ipv6_pool (
                address     TEXT PRIMARY KEY,
                proxy_id    INTEGER,
                allocated_at DATETIME,
                FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS bot_users (
                telegram_id TEXT PRIMARY KEY,
                username    TEXT,
                role        TEXT DEFAULT 'user',
                added_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS operation_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                action      TEXT NOT NULL,
                target_id   INTEGER,
                target_ip   TEXT,
                result      TEXT,
                detail      TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_proxies_status ON proxies(status);
            CREATE INDEX IF NOT EXISTS idx_proxies_ipv6 ON proxies(ipv6_addr);
            CREATE INDEX IF NOT EXISTS idx_port_allocations_proxy ON port_allocations(proxy_id);
            CREATE INDEX IF NOT EXISTS idx_logs_action ON operation_logs(action);
            CREATE INDEX IF NOT EXISTS idx_logs_created ON operation_logs(created_at);
        """)
        await db.commit()
    finally:
        await db.close()


async def log_operation(action: str, target_id: int = None, target_ip: str = None,
                        result: str = "success", detail: str = ""):
    import asyncio
    for attempt in range(3):
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO operation_logs (action, target_id, target_ip, result, detail) VALUES (?, ?, ?, ?, ?)",
                (action, target_id, target_ip, result, detail)
            )
            await db.commit()
            break
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.1 * (attempt + 1))
            else:
                pass
        finally:
            await db.close()
