import abc
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import Response

_Func = Callable[..., Any]


class KeyBuilder(Protocol):
    def __call__(
        self,
        __function: _Func,
        __namespace: str = ...,
        *,
        request: Request | None = ...,
        response: Response | None = ...,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Awaitable[str] | str:
        ...


class Backend(abc.ABC):
    @abc.abstractmethod
    async def get_with_ttl(self, key: str) -> tuple[int, bytes | None]:
        ...

    @abc.abstractmethod
    async def get(self, key: str) -> bytes | None:
        ...

    @abc.abstractmethod
    async def set(self, key: str, value: bytes, expire: int | None = None) -> None:
        ...

    def lock(self, key: str, timeout: int) -> AbstractAsyncContextManager[Any]:
        return AsyncExitStack()  # pyright: ignore [reportUnknownVariableType]

    @abc.abstractmethod
    async def clear(self, namespace: str | None = None, key: str | None = None) -> int:
        ...
