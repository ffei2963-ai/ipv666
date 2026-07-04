import json

from src.db.database import get_db
from src.utils.logger import logger


class AuthManager:
    def __init__(self, admin_ids: list[str] = None):
        self.admin_ids = set(admin_ids or [])

    async def is_authorized(self, telegram_id: str) -> bool:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT telegram_id, role FROM bot_users WHERE telegram_id = ?",
                (str(telegram_id),)
            )
            row = await cursor.fetchone()
            if row:
                return True
            if str(telegram_id) in self.admin_ids:
                return True
            return False
        finally:
            await db.close()

    async def add_user(self, telegram_id: str, username: str = "", role: str = "user"):
        db = await get_db()
        try:
            await db.execute(
                "INSERT OR REPLACE INTO bot_users (telegram_id, username, role) VALUES (?, ?, ?)",
                (str(telegram_id), username, role)
            )
            await db.commit()
            logger.info(f"Added bot user: {telegram_id} ({username}) as {role}")
        finally:
            await db.close()

    async def add_admins_from_env(self):
        for admin_id in self.admin_ids:
            await self.add_user(str(admin_id), role="admin")

    async def list_users(self) -> list[dict]:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT telegram_id, username, role, added_at FROM bot_users"
            )
            rows = await cursor.fetchall()
            return [{"telegram_id": r[0], "username": r[1], "role": r[2], "added_at": r[3]} for r in rows]
        finally:
            await db.close()

    async def remove_user(self, telegram_id: str):
        db = await get_db()
        try:
            await db.execute("DELETE FROM bot_users WHERE telegram_id = ?", (str(telegram_id),))
            await db.commit()
        finally:
            await db.close()
