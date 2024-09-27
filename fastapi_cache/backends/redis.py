from contextlib import AbstractAsyncContextManager
from functools import cached_property
from typing import Any, Union

from redis.asyncio import Redis, RedisCluster
from redis.asyncio.lock import Lock

from fastapi_cache.types import Backend


class RedisBackend(Backend):
    def __init__(
        self,
        redis: Union["Redis[bytes]", "RedisCluster[bytes]", None] = None,
        redis_write: Union["Redis[bytes]", None] = None,
        redis_read: Union["Redis[bytes]", None] = None,
    ):
        if not (redis_write and redis_read) and not redis:
            raise ValueError("Either Redis of redis read/write instances should be provided!")

        self.redis = redis
        self._redis_write = redis_write
        self._redis_read = redis_read
        self.is_cluster: bool = isinstance(redis, RedisCluster)

    @cached_property
    def redis_write(self) -> "Redis[bytes]":
        if self._redis_write:
            return self._redis_write
        return self.redis  # type: ignore[return-value]

    @cached_property
    def redis_read(self) -> "Redis[bytes]":
        if self._redis_read:
            return self._redis_read
        return self.redis  # type: ignore[return-value]

    async def get_with_ttl(self, key: str) -> tuple[int, bytes | None]:
        async with self.redis_read.pipeline(transaction=not self.is_cluster) as pipe:
            return await pipe.ttl(key).get(key).execute()  # type: ignore[no-any-return]

    async def get(self, key: str) -> bytes | None:
        return await self.redis_read.get(key)

    async def set(self, key: str, value: bytes, expire: int | None = None) -> None:
        await self.redis_write.set(key, value, ex=expire)

    def lock(self, key: str, timeout: int) -> AbstractAsyncContextManager[Any]:
        lock_key = f"{key}::lock"

        return Lock(self.redis_write, lock_key, timeout=timeout)

    async def clear(self, namespace: str | None = None, key: str | None = None) -> int:
        if namespace:
            lua = f"for i, name in ipairs(redis.call('KEYS', '{namespace}:*')) do redis.call('DEL', name); end"
            return await self.redis_write.eval(lua, numkeys=0)  # type: ignore[no-any-return,no-untyped-call]
        elif key:
            return await self.redis_write.delete(key)
        return 0
