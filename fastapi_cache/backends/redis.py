import textwrap
from functools import cached_property
from typing import TYPE_CHECKING, Any, Union

from msgspec import UNSET, UnsetType
from redis.asyncio import Redis, RedisCluster
from redis.asyncio.lock import Lock

from fastapi_cache.helpers.invariant import invariant
from fastapi_cache.types import Backend

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager


class RedisBackend(Backend):
    DELETE_BY_KEYS_SCRIPT = textwrap.dedent("""
    local count = 0
    for _,k in ipairs(redis.call('keys', ARGV[1])) do
        count = count + redis.call('del', k)
    end
    return count""").strip()
    DELETE_BY_SCAN_SCRIPT = textwrap.dedent("""
    local cursor = 0
    local count = 0
    repeat
        local result = redis.call('SCAN', cursor, 'MATCH', ARGV[1])
        for _, key in ipairs(result[2]) do
            count = count + redis.call('UNLINK', key)
        end
        cursor = tonumber(result[1])
    until cursor == 0
    return count
    """).strip()

    def __init__(
        self,
        redis: Union["Redis[bytes]", "RedisCluster[bytes]", None] = None,
        redis_write: Union["Redis[bytes]", None] = None,
        redis_read: Union["Redis[bytes]", None] = None,
        use_scan: bool | UnsetType = UNSET,
        use_python_impl: bool | UnsetType = UNSET,
    ):
        """Initialize Redis backend.

        Args:
            redis: redis client instance.
            redis_write: separate client instance for write operations.
            redis_read: separate client instance for read operations.
            use_scan: whether to enforce `scan` when deleting keys by `namespace`.
            use_python_impl: whether to use Python implementation instead of LUA scripts
                for key deletion (useful for environments where LUA eval is restricted).
        """

        if not (redis_write and redis_read) and not redis:
            raise ValueError("Either Redis of redis read/write instances should be provided!")

        self.redis = redis
        self._redis_write = redis_write
        self._redis_read = redis_read
        self.is_cluster: bool = isinstance(redis, RedisCluster)
        self.use_scan = invariant(use_scan, self.is_cluster)
        # `scan` has non-deterministic output, so it's not supported in a cluster
        self.use_python_impl = invariant(use_python_impl, self.is_cluster)

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

    def lock(self, key: str, timeout: int) -> "AbstractAsyncContextManager[Any]":
        lock_key = f"{key}::lock"

        return Lock(self.redis_write, lock_key, timeout=timeout)

    async def _clear_by_keys_python(self, match: str) -> int:
        """Python implementation of DELETE_BY_KEYS_SCRIPT.

        Args:
            match: The match pattern to match keys against.

        Returns:
            Number of keys deleted.
        """
        keys = await self.redis_write.keys(match)
        if not keys:
            return 0
        return await self.redis_write.delete(*keys)

    async def _clear_by_scan_python(self, match: str) -> int:
        """Python implementation of DELETE_BY_SCAN_SCRIPT.

        Args:
            match: The match pattern to match keys against.

        Returns:
            Number of keys deleted.
        """
        count = 0
        cursor = 0
        while True:
            cursor, keys = await self.redis_write.scan(cursor=cursor, match=match, count=100)
            if keys:
                count += await self.redis_write.unlink(*keys)
            if cursor == 0:
                break
        return count

    async def clear_namespace(self, namespace: str) -> int:
        """Clear all keys in the given namespace.
        Args:
            namespace: namespace/prefix to clear.

        Returns:
            Number of keys deleted.
        """

        namespace = f"{namespace}:*"
        if self.use_python_impl:
            if self.use_scan:
                return await self._clear_by_scan_python(namespace)
            return await self._clear_by_keys_python(namespace)
        lua = self.DELETE_BY_SCAN_SCRIPT if self.use_scan else self.DELETE_BY_KEYS_SCRIPT
        return await self.redis_write.eval(lua, 0, namespace)  # type: ignore[no-any-return,no-untyped-call]

    async def clear(self, namespace: str | None = None, key: str | None = None) -> int:
        if namespace:
            return await self.clear_namespace(namespace)
        elif key:
            return await self.redis_write.delete(key)
        return 0
