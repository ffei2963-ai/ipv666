import asyncio
from typing import Callable, Awaitable

from src.utils.logger import logger


class RollbackError(Exception):
    pass


class TransactionContext:
    def __init__(self):
        self.rollback_steps: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        self.completed = False

    def add_step(self, name: str, rollback_fn: Callable[[], Awaitable[None]]):
        self.rollback_steps.append((name, rollback_fn))

    async def rollback(self):
        logger.warning("Starting rollback...")
        for name, fn in reversed(self.rollback_steps):
            try:
                logger.info(f"Rolling back: {name}")
                await fn()
            except Exception as e:
                logger.error(f"Rollback step '{name}' failed: {e}")

    async def close(self):
        if not self.completed:
            await self.rollback()


def rollback_step(name: str):
    def decorator(func):
        async def wrapper(self, *args, **kwargs):
            result = await func(self, *args, **kwargs)
            return result
        wrapper._rollback_name = name
        return wrapper
    return decorator
