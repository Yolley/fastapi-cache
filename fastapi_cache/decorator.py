import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import Parameter, Signature, isawaitable, iscoroutinefunction
from typing import (
    ParamSpec,
    TypeVar,
    cast,
)

from fastapi.concurrency import run_in_threadpool
from fastapi.dependencies.utils import (
    get_typed_return_annotation,
    get_typed_signature,
)
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_304_NOT_MODIFIED

from fastapi_cache import FastAPICache
from fastapi_cache.coder import Coder
from fastapi_cache.types import KeyBuilder

logger: logging.Logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
P = ParamSpec("P")
R = TypeVar("R")


def _augment_signature(signature: Signature, *extra: Parameter) -> Signature:
    if not extra:
        return signature

    parameters = list(signature.parameters.values())
    variadic_keyword_params: list[Parameter] = []
    while parameters and parameters[-1].kind is Parameter.VAR_KEYWORD:
        variadic_keyword_params.append(parameters.pop())

    return signature.replace(
        parameters=[*parameters, *extra, *variadic_keyword_params]
    )


def _locate_param(
    sig: Signature, dep: Parameter, to_inject: list[Parameter]
) -> Parameter:
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


def _uncacheable(request: Request | None) -> bool:
    """Determine if this request should not be cached

    Returns true if:
    - Caching has been disabled globally
    - This is not a GET request
    - The request has a Cache-Control header with a value of "no-store"

    """
    if not FastAPICache.get_enable():
        return True
    if request is None:
        return False
    if request.method != "GET":
        return True
    return request.headers.get("Cache-Control") == "no-store"


def cache(
    expire: int | None = None,
    coder: type[Coder] | None = None,
    key_builder: KeyBuilder | None = None,
    namespace: str = "",
    injected_dependency_namespace: str = "__fastapi_cache",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    cache all function
    :param injected_dependency_namespace:
    :param namespace:
    :param expire:
    :param coder:
    :param key_builder:

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

    def wrapper(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        # get_typed_signature ensures that any forward references are resolved first
        wrapped_signature = get_typed_signature(func)
        to_inject: list[Parameter] = []
        request_param = _locate_param(
            wrapped_signature, injected_request, to_inject
        )
        response_param = _locate_param(
            wrapped_signature, injected_response, to_inject
        )
        return_type = get_typed_return_annotation(func)

        @wraps(func)
        async def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            nonlocal coder
            nonlocal expire
            nonlocal key_builder

            async def ensure_async_func(*args: P.args, **kwargs: P.kwargs) -> R:
                """Run cached sync functions in thread pool just like FastAPI."""
                # if the wrapped function does NOT have request or response in
                # its function signature, make sure we don't pass them in as
                # keyword arguments
                kwargs.pop(injected_request.name, None)
                kwargs.pop(injected_response.name, None)

                if iscoroutinefunction(func):
                    # async, return as is.
                    # unintuitively, we have to await once here, so that caller
                    # does not have to await twice. See
                    # https://stackoverflow.com/a/59268198/532513
                    return await func(*args, **kwargs)
                else:
                    # sync, wrap in thread and return async
                    # see above why we have to await even although caller also awaits.
                    return await run_in_threadpool(func, *args, **kwargs)  # type: ignore[arg-type]

            copy_kwargs = kwargs.copy()
            request: Request | None = copy_kwargs.pop(request_param.name, None)  # type: ignore[assignment]
            response: Response | None = copy_kwargs.pop(
                response_param.name, None
            )  # type: ignore[assignment]

            if _uncacheable(request):
                return await ensure_async_func(*args, **kwargs)

            prefix = FastAPICache.get_prefix()
            coder = coder or FastAPICache.get_coder()
            expire = expire or FastAPICache.get_expire()
            key_builder = key_builder or FastAPICache.get_key_builder()
            backend = FastAPICache.get_backend()
            cache_status_header = FastAPICache.get_cache_status_header()

            cache_key = key_builder(
                func,
                f"{prefix}:{namespace}",
                request=request,
                response=response,
                args=args,
                kwargs=copy_kwargs,
            )
            if isawaitable(cache_key):
                cache_key = await cache_key
            assert isinstance(cache_key, str)  # noqa: S101  # assertion is a type guard

            try:
                ttl, cached = await backend.get_with_ttl(cache_key)
            except Exception:
                logger.warning(
                    f"Error retrieving cache key '{cache_key}' from backend:",
                    exc_info=True,
                )
                ttl, cached = 0, None

            if cached is None  or (request is not None and request.headers.get("Cache-Control") == "no-cache") :  # cache miss
                result = await ensure_async_func(*args, **kwargs)
                to_cache = coder.encode(result)

                try:
                    await backend.set(cache_key, to_cache, expire)
                except Exception:
                    logger.warning(
                        f"Error setting cache key '{cache_key}' in backend:",
                        exc_info=True,
                    )

                if response:
                    response.headers.update(
                        {
                            "Cache-Control": f"max-age={expire}",
                            "ETag": f"W/{hash(to_cache)}",
                            cache_status_header: "MISS",
                        }
                    )

                return result

            if response:
                etag = f"W/{hash(cached)}"
                response.headers.update(
                    {
                        "Cache-Control": f"max-age={ttl}",
                        "ETag": etag,
                        cache_status_header: "HIT",
                    }
                )

                if_none_match = request and request.headers.get("if-none-match")
                if if_none_match == etag:
                    response.status_code = HTTP_304_NOT_MODIFIED
                    # TODO: do not type it because it's a special case and I am not sure how to overload it
                    return response  # type: ignore

            return cast(R, coder.decode_as_type(cached, type_=return_type))

        inner.__signature__ = _augment_signature(wrapped_signature, *to_inject)  # type: ignore[attr-defined]

        return inner

    return wrapper
