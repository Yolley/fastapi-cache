import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, ClassVar

from fastapi_cache.types import Backend


@dataclass
class Value:
    data: bytes
    ttl_ts: int


class InMemoryBackend(Backend):
    _store: ClassVar[dict[str, Value]] = {}
    _locks: ClassVar[dict[str, asyncio.Lock]] = {}
    _check_lock = asyncio.Lock()

    @asynccontextmanager
    async def get_lock(self, name: str, timeout: int) -> AsyncGenerator[None, None]:
        async with self._check_lock:
            if name not in self._locks:
                self._locks[name] = asyncio.Lock()
        result: bool
        try:
            result = await asyncio.wait_for(self._locks[name].acquire(), timeout)
        except TimeoutError:
            result = False
        try:
            yield
        finally:
            if result:
                self._locks[name].release()
                async with self._check_lock:
                    if name in self._locks and not getattr(self._locks[name], "_waiters", None):
                        del self._locks[name]

    @property
    def _now(self) -> int:
        return int(time.time())

    def _get(self, key: str) -> Value | None:
        v = self._store.get(key)
        if v:
            if v.ttl_ts < self._now:
                del self._store[key]
            else:
                return v
        return None

    async def get_with_ttl(self, key: str) -> tuple[int, bytes | None]:
        v = self._get(key)
        if v:
            return v.ttl_ts - self._now, v.data
        return 0, None

    async def get(self, key: str) -> bytes | None:
        v = self._get(key)
        if v:
            return v.data
        return None

    async def set(self, key: str, value: bytes, expire: int | None = None) -> None:
        self._store[key] = Value(value, self._now + (expire or 0))

    def lock(self, key: str, timeout: int) -> AbstractAsyncContextManager[Any]:
        lock_key = f"{key}::lock"

        return self.get_lock(lock_key, timeout)

    async def clear(self, namespace: str | None = None, key: str | None = None) -> int:
        count = 0
        if namespace:
            keys = list(self._store.keys())
            for key in keys:
                if key.startswith(namespace):
                    del self._store[key]
                    count += 1
        elif key:
            del self._store[key]
            count += 1
        return count
