import logging
import typing
from collections.abc import Awaitable, Callable, Generator
from contextlib import AsyncExitStack, contextmanager
from contextvars import Token
from functools import partial, update_wrapper
from inspect import Parameter, Signature, isawaitable, iscoroutinefunction, markcoroutinefunction
from types import MappingProxyType
from typing import (
    Any,
    Generic,
    Literal,
    ParamSpec,
    TypeVar,
    cast,
    overload,
)

from fastapi.concurrency import run_in_threadpool
from fastapi.dependencies.utils import (
    get_typed_return_annotation,
    get_typed_signature,
)
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_304_NOT_MODIFIED

from fastapi_cache import Backend, FastAPICache
from fastapi_cache.coder import Coder
from fastapi_cache.context import CacheCtx, CacheCtxWithOptional, cache_ctx_var
from fastapi_cache.types import KeyBuilder

logger: logging.Logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
P = ParamSpec("P")
R = TypeVar("R")
# According to [RFC 2616](https://www.ietf.org/rfc/rfc2616.txt)
MAX_AGE_NEVER_EXPIRES = 31536000


class Undefined:
    pass


UNDEFINED = Undefined()


def _augment_signature(signature: Signature, *extra: Parameter) -> Signature:
    if not extra:
        return signature

    parameters = list(signature.parameters.values())
    variadic_keyword_params: list[Parameter] = []
    while parameters and parameters[-1].kind is Parameter.VAR_KEYWORD:
        variadic_keyword_params.append(parameters.pop())

    return signature.replace(parameters=[*parameters, *extra, *variadic_keyword_params])


def _locate_param(sig: Signature, dep: Parameter, to_inject: list[Parameter]) -> Parameter:
    """Locate an existing parameter in the decorated endpoint

    If not found, returns the injectable parameter, and adds it to the to_inject list.

    """
    param = next(
        (p for p in sig.parameters.values() if p.annotation is dep.annotation),
        None,
    )
    if param is None:
        to_inject.append(dep)
        param = dep
    return param


def _uncacheable(request: Request | None, bypass_cache_control: bool) -> bool:
    """Determine if this request should not be cached

    Returns true if:
    - Caching has been disabled globally
    - This is not a GET request
    - The request has a Cache-Control header with a value of "no-store"

    """
    if not FastAPICache.get_enable():
        return True
    if request is None or bypass_cache_control:
        return False
    if request.method != "GET":
        return True
    return request.headers.get("Cache-Control") == "no-store"


async def _get_cached(backend: Backend, cache_key: str) -> tuple[int, Any]:
    try:
        ttl, cached = await backend.get_with_ttl(cache_key)
    except Exception:
        logger.warning(
            f"Error retrieving cache key '{cache_key}' from backend:",
            exc_info=True,
        )
        ttl, cached = 0, None
    return ttl, cached


def _get_max_age(ttl: int | None) -> int:
    """Get the Cache-Control max-age value for a given TTL.

    TTL could be negative if returned from Redis, for example. In this case the cache never expires."""

    if ttl is None or ttl < 0:
        return MAX_AGE_NEVER_EXPIRES
    return ttl


def cache(
    expire: int | None | Undefined = UNDEFINED,
    coder: type[Coder] | Undefined = UNDEFINED,
    key_builder: KeyBuilder | Undefined = UNDEFINED,
    namespace: str = "",
    with_lock: bool = False,
    lock_timeout: int = 60,
    bypass_cache_control: bool = False,
    injected_dependency_namespace: str = "__fastapi_cache",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    cache-all function
    :param injected_dependency_namespace:
    :param namespace:
    :param expire:
    :param coder:
    :param key_builder:
    :param with_lock:
    :param lock_timeout:
    :param bypass_cache_control

    :return:
    """

    injected_request = Parameter(
        name=f"{injected_dependency_namespace}_request",
        annotation=Request,
        kind=Parameter.KEYWORD_ONLY,
    )
    injected_response = Parameter(
        name=f"{injected_dependency_namespace}_response",
        annotation=Response,
        kind=Parameter.KEYWORD_ONLY,
    )

    ctx: CacheCtxWithOptional = {
        "namespace": namespace,
        "with_lock": with_lock,
        "lock_timeout": lock_timeout,
        "bypass_cache_control": bypass_cache_control,
        "injected_request": injected_request,
        "injected_response": injected_response,
    }

    if not isinstance(key_builder, Undefined):
        ctx["key_builder"] = key_builder
    if not isinstance(expire, Undefined):
        ctx["expire"] = expire
    if not isinstance(coder, Undefined):
        ctx["coder"] = coder

    return partial(CachedFunc, ctx)  # type: ignore[return-value]


class CachedFunc(Generic[P, R]):
    def __init__(
        self,
        ctx: CacheCtxWithOptional,
        func: Callable[P, Awaitable[R]],
    ) -> None:
        wrapped_signature = get_typed_signature(func)

        to_inject: list[Parameter] = []
        self.request_param = _locate_param(wrapped_signature, ctx["injected_request"], to_inject)
        self.response_param = _locate_param(wrapped_signature, ctx["injected_response"], to_inject)
        self.return_type = get_typed_return_annotation(func)

        self._ctx = MappingProxyType(ctx)
        self._is_ctx_set = False
        self.func = func

        update_wrapper(self, func)
        markcoroutinefunction(self)
        self.__signature__ = _augment_signature(wrapped_signature, *to_inject)

        self.__ctx_token: Token[CacheCtx] | None = None

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        with self.__ctx_token_cycle():
            return await self.inner(*args, **kwargs)  # type: ignore[return-value]

    @contextmanager
    def __ctx_token_cycle(self) -> Generator[None, None, None]:
        self.__ctx_token = None
        yield
        if self.__ctx_token:
            cache_ctx_var.reset(self.__ctx_token)

    @property
    def global_ctx(self) -> CacheCtx:
        """Cache will be set on the first function call.

        Useful when the decorator is executed before Cache is instantiated."""

        if self._is_ctx_set:
            return typing.cast(CacheCtx, self._ctx)  # pyright: ignore[reportUnknownMemberType]
        ctx = typing.cast(CacheCtx, dict(self._ctx))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        ctx.setdefault("coder", FastAPICache.get_coder())
        ctx.setdefault("expire", FastAPICache.get_expire())
        ctx.setdefault("key_builder", FastAPICache.get_key_builder())
        self._ctx = MappingProxyType(ctx)
        self._is_ctx_set = True
        return self.global_ctx

    def get_local_ctx(self) -> CacheCtx:
        return typing.cast(CacheCtx, dict(self.global_ctx))

    def get_ctx(self) -> CacheCtx:
        """Returns either a global context or a local one.

        Local context should be set only if we actually call the `func`."""

        try:
            return cache_ctx_var.get()
        except LookupError:
            return self.global_ctx

    async def ensure_async_func(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Run cached sync functions in a thread pool just like FastAPI

        Sets local context that may be optionally used and updated by the function."""
        ctx = self.get_local_ctx()
        self.__ctx_token = cache_ctx_var.set(ctx)

        # if the wrapped function does NOT have a request or response in
        # its function signature, make sure we don't pass them in as
        # keyword arguments
        kwargs.pop(ctx["injected_request"].name, None)
        kwargs.pop(ctx["injected_response"].name, None)

        if iscoroutinefunction(self.func):
            # async, return as is.
            # unintuitively, we have to await once here, so that caller
            # does not have to await twice. See
            # https://stackoverflow.com/a/59268198/532513
            return await self.func(*args, **kwargs)
        # sync, wrap in thread and return async
        # see above why we have to await even although caller also awaits.
        return await run_in_threadpool(self.func, *args, **kwargs)  # type: ignore[arg-type]

    async def get_cached_or_call(
        self, cache_key: str, no_cache: bool, *args: P.args, **kwargs: P.kwargs
    ) -> tuple[R, int | None, Literal[False]] | tuple[Any, int | None, Literal[True]]:
        """Get the cached value or call the function if not cached."""

        try:
            print(cache_ctx_var.get())
        except LookupError:
            pass
        ctx = self.get_ctx()

        backend = FastAPICache.get_backend()

        ttl, cached = await _get_cached(backend, cache_key)
        if not no_cache and cached is not None:
            return cached, ttl, True

        if ctx["with_lock"]:
            lock = backend.lock(cache_key, ctx["lock_timeout"])
        else:
            lock = AsyncExitStack()

        async with lock:
            if not no_cache and ctx["with_lock"]:
                ttl, cached = await _get_cached(backend, cache_key)
                if cached is not None:
                    return cached, ttl, True

            result = await self.ensure_async_func(*args, **kwargs)
            ctx = self.get_ctx()

            return result, ctx["expire"], False

    @overload
    def build_cached_result(self, cached: Any, ttl: int | None, headers: Headers | dict[str, str], response: None) -> R:
        ...

    @overload
    def build_cached_result(
        self, cached: Any, ttl: int | None, headers: Headers | dict[str, str], response: Response
    ) -> Response:
        ...

    def build_cached_result(
        self, cached: Any, ttl: int | None, headers: Headers | dict[str, str], response: Response | None
    ) -> R | Response:
        cache_status_header = FastAPICache.get_cache_status_header()

        etag = f"W/{hash(cached)}"
        if response and (if_none_match := headers.get("if-none-match")) and (if_none_match == etag):
            response.headers.update(
                {
                    "Cache-Control": f"max-age={ttl}",
                    "ETag": etag,
                    cache_status_header: "HIT",
                }
            )

            response.status_code = HTTP_304_NOT_MODIFIED
            return response

        cached_decoded = cast(R, self.global_ctx["coder"].decode_as_type(cached, type_=self.return_type))
        if isinstance(cached_decoded, Response):
            response = cached_decoded

        if response:
            response.headers.update(
                {
                    "Cache-Control": f"max-age={_get_max_age(ttl)}",
                    "ETag": etag,
                    cache_status_header: "HIT",
                }
            )
        return cached_decoded

    async def inner(self, *args: P.args, **kwargs: P.kwargs) -> R | Response:
        ctx = self.get_ctx()

        copy_kwargs = kwargs.copy()
        request: Request | None = copy_kwargs.pop(self.request_param.name, None)  # type: ignore[assignment]
        response: Response | None = copy_kwargs.pop(self.response_param.name, None)  # type: ignore[assignment]

        if _uncacheable(request, ctx["bypass_cache_control"]):
            return await self.ensure_async_func(*args, **kwargs)

        headers: Headers | dict[str, str] = request.headers if request else {}
        no_cache = not ctx["bypass_cache_control"] and headers.get("Cache-Control") == "no-cache"
        prefix = FastAPICache.get_prefix()
        backend = FastAPICache.get_backend()
        cache_status_header = FastAPICache.get_cache_status_header()

        cache_key = ctx["key_builder"](
            self.func,
            f"{prefix}:{ctx['namespace']}",
            request=request,
            response=response,
            args=args,
            kwargs=copy_kwargs,
        )
        if isawaitable(cache_key):
            cache_key = await cache_key
        assert isinstance(cache_key, str)  # noqa: S101 # assertion is a type guard

        result, ttl, from_cache = await self.get_cached_or_call(cache_key, no_cache, *args, **kwargs)

        if from_cache:
            return self.build_cached_result(result, ttl, headers, response)

        ctx = self.get_ctx()
        to_cache = ctx["coder"].encode(result)

        try:
            await backend.set(cache_key, to_cache, ttl)
        except Exception as e:
            logger.warning(
                "Error setting cache key '%s' in backend: '%s",
                cache_key,
                e,
                exc_info=True,
            )

        if isinstance(result, Response):
            response = result
        if response:
            response.headers.update(
                {
                    "Cache-Control": f"max-age={_get_max_age(ttl)}",
                    "ETag": f"W/{hash(to_cache)}",
                    cache_status_header: "MISS",
                }
            )

        return result
