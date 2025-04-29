from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

_Func = Callable[..., Any]


class KeyBuilder(Protocol):
    def __call__(
        self,
        __function: _Func,
        __namespace: str = ...,
        *,
        request: "Request | None" = ...,
        response: "Response | None" = ...,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Awaitable[str] | str: ...
