# Because this project supports python 3.7 and up, Pyright treats importlib as
# an external library and so needs to be told to ignore the type issues it sees.
from importlib.metadata import version
from typing import ClassVar

from fastapi_cache.coder import Coder, JsonCoder
from fastapi_cache.key_builder import default_key_builder
from fastapi_cache.types import Backend, KeyBuilder

__version__ = version("fastapi-cache2-fork")  # pyright: ignore[reportUnknownVariableType]
__all__ = [
    "Backend",
    "Coder",
    "FastAPICache",
    "JsonCoder",
    "KeyBuilder",
    "default_key_builder",
]


class FastAPICache:
    _backend: ClassVar[Backend | None] = None
    _prefix: ClassVar[str | None] = None
    _expire: ClassVar[int | None] = None
    _init: ClassVar[bool] = False
    _coder: ClassVar[type[Coder] | None] = None
    _key_builder: ClassVar[KeyBuilder | None] = None
    _cache_status_header: ClassVar[str | None] = None
    _enable: ClassVar[bool] = True

    @classmethod
    def init(
        cls,
        backend: Backend,
        prefix: str = "",
        expire: int | None = None,
        coder: type[Coder] = JsonCoder,
        key_builder: KeyBuilder = default_key_builder,
        cache_status_header: str = "X-FastAPI-Cache",
        enable: bool = True,
    ) -> None:
        if cls._init:
            return
        cls._init = True
        cls._backend = backend
        cls._prefix = prefix
        cls._expire = expire
        cls._coder = coder
        cls._key_builder = key_builder
        cls._cache_status_header = cache_status_header
        cls._enable = enable

    @classmethod
    def reset(cls) -> None:
        cls._init = False
        cls._backend = None
        cls._prefix = None
        cls._expire = None
        cls._coder = None
        cls._key_builder = None
        cls._cache_status_header = None
        cls._enable = True

    @classmethod
    def get_backend(cls) -> Backend:
        assert cls._backend, "You must call init first!"  # noqa: S101
        return cls._backend

    @classmethod
    def get_prefix(cls) -> str:
        assert cls._prefix is not None, "You must call init first!"  # noqa: S101
        return cls._prefix

    @classmethod
    def get_expire(cls) -> int | None:
        return cls._expire

    @classmethod
    def get_coder(cls) -> type[Coder]:
        assert cls._coder, "You must call init first!"  # noqa: S101
        return cls._coder

    @classmethod
    def get_key_builder(cls) -> KeyBuilder:
        assert cls._key_builder, "You must call init first!"  # noqa: S101
        return cls._key_builder

    @classmethod
    def get_cache_status_header(cls) -> str:
        assert cls._cache_status_header, "You must call init first!"  # noqa: S101
        return cls._cache_status_header

    @classmethod
    def get_enable(cls) -> bool:
        return cls._enable

    @classmethod
    async def clear(
        cls, namespace: str | None = None, key: str | None = None
    ) -> int:
        assert (  # noqa: S101
            cls._backend and cls._prefix is not None
        ), "You must call init first!"
        namespace = cls._prefix + (":" + namespace if namespace else "")
        return await cls._backend.clear(namespace, key)
