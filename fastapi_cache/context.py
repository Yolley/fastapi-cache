from contextvars import ContextVar
from inspect import Parameter

from msgspec import UNSET, Struct, UnsetType

from fastapi_cache.coder import Coder
from fastapi_cache.types import KeyBuilder


class CacheCtxCommon(Struct):
    namespace: str
    with_lock: bool
    lock_timeout: int
    bypass_cache_control: bool
    injected_request: Parameter
    injected_response: Parameter


class CacheCtxWithOptional(CacheCtxCommon):
    expire: int | None | UnsetType = UNSET
    coder: type[Coder] | UnsetType = UNSET
    key_builder: KeyBuilder | UnsetType = UNSET


class CacheCtx(CacheCtxCommon):
    expire: int | None
    coder: type[Coder]
    key_builder: KeyBuilder


class CacheCtxFrozen(CacheCtx, frozen=True):  # type: ignore[misc]
    pass


cache_ctx_var: ContextVar[CacheCtx] = ContextVar("cache_ctx")


def get_cache_ctx() -> CacheCtx:
    try:
        return cache_ctx_var.get()
    except LookupError as e:
        raise RuntimeError("Cache ctx it not set!") from e
