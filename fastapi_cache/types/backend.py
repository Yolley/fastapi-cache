import abc
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Any


class Backend(abc.ABC):
    @abc.abstractmethod
    async def get_with_ttl(self, key: str) -> tuple[int, bytes | None]: ...

    @abc.abstractmethod
    async def get(self, key: str) -> bytes | None: ...

    @abc.abstractmethod
    async def set(self, key: str, value: bytes, expire: int | None = None) -> None: ...

    def lock(self, key: str, timeout: int) -> AbstractAsyncContextManager[Any]:
        return AsyncExitStack()  # pyright: ignore [reportUnknownVariableType]

    @abc.abstractmethod
    async def clear(self, namespace: str | None = None, key: str | None = None) -> int: ...
