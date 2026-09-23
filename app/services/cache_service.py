from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

CACHE_BACKEND = os.getenv("CACHE_BACKEND", "memory").lower()
logger = logging.getLogger(__name__)


class CacheService:
    def __init__(self) -> None:
        self._memory: dict[str, tuple[float | None, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._firestore = None

    async def _get_firestore(self):
        if CACHE_BACKEND != "firestore":
            return None
        if self._firestore is None:
            try:
                from google.cloud import firestore
                self._firestore = firestore.AsyncClient()
            except Exception:
                logger.exception("Firestore cache client initialization failed; memory cache fallback enabled")
                return None
        return self._firestore

    @staticmethod
    def _doc_id(namespace: str, key: str) -> str:
        return f"{namespace}__{key.replace('/', '_')}"

    async def get(self, namespace: str, key: str) -> Any | None:
        memory_key = f"{namespace}:{key}"
        cached = self._memory.get(memory_key)
        if cached:
            expires_at, value = cached
            if expires_at is None or expires_at > time.time():
                return value
            self._memory.pop(memory_key, None)

        db = await self._get_firestore()
        if db is None:
            return None

        try:
            snap = await db.collection("travel_cache").document(self._doc_id(namespace, key)).get()
        except Exception:
            logger.exception("Firestore cache read failed; continuing with memory cache")
            return None
        if not snap.exists:
            return None

        data = snap.to_dict() or {}
        expires_at = data.get("expires_at")
        if expires_at is not None and float(expires_at) <= time.time():
            return None

        value = data.get("value")
        self._memory[memory_key] = (float(expires_at) if expires_at else None, value)
        return value

    async def set(self, namespace: str, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        memory_key = f"{namespace}:{key}"
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        self._memory[memory_key] = (expires_at, value)

        db = await self._get_firestore()
        if db is None:
            return

        try:
            await db.collection("travel_cache").document(self._doc_id(namespace, key)).set({
                "value": value,
                "expires_at": expires_at,
                "updated_at": time.time(),
            })
        except Exception:
            logger.exception("Firestore cache write failed; value retained in memory cache only")

    async def get_or_create(
        self,
        namespace: str,
        key: str,
        factory: Callable[[], Awaitable[Any]],
        ttl_seconds: int | None = None,
    ) -> tuple[Any, bool]:
        value = await self.get(namespace, key)
        if value is not None:
            return value, True

        lock_key = f"{namespace}:{key}"
        async with self._locks[lock_key]:
            value = await self.get(namespace, key)
            if value is not None:
                return value, True

            value = await factory()
            await self.set(namespace, key, value, ttl_seconds)
            return value, False


cache = CacheService()
