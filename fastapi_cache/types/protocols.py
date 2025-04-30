from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

_Func = Callable[..., Any]


@runtime_checkable
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
