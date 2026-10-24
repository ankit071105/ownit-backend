"""Tiny in-memory TTL cache. Saves GitHub + Groq rate limits.

Render free instances restart often, so this is "best effort" — good enough
for a portfolio project. Swap with Redis if traffic grows.
"""
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int, max_items: int = 500):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self.max_items:
            # drop the oldest entry
            oldest = min(self._store, key=lambda k: self._store[k][0])
            self._store.pop(oldest, None)
        self._store[key] = (time.time() + self.ttl, value)
