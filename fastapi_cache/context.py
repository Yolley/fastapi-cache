from contextvars import ContextVar
from inspect import Parameter
from typing import NotRequired, TypedDict

from fastapi_cache.coder import Coder
from fastapi_cache.types import KeyBuilder


class CacheCtxCommon(TypedDict):
    namespace: str
    with_lock: bool
    lock_timeout: int
    bypass_cache_control: bool
    injected_request: Parameter
    injected_response: Parameter


class CacheCtxWithOptional(CacheCtxCommon):
    prefix: NotRequired[str]
    expire: NotRequired[int | None]
    coder: NotRequired[type[Coder]]
    key_builder: NotRequired[KeyBuilder]


class CacheCtx(CacheCtxCommon):
    prefix: str
    expire: int | None
    coder: type[Coder]
    key_builder: KeyBuilder


cache_ctx_var: ContextVar[CacheCtx] = ContextVar("cache_ctx")


def get_cache_ctx() -> CacheCtx:
    try:
        return cache_ctx_var.get()
    except LookupError as e:
        raise RuntimeError("Cache ctx it not set!") from e
