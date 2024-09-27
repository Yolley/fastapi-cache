from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session", autouse=True)
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _init_cache() -> Generator[None, None, None]:  # pyright: ignore[reportUnusedFunction]
    FastAPICache.init(InMemoryBackend())
    yield
    FastAPICache.reset()


@pytest.fixture(scope="session", autouse=True)
async def app() -> AsyncGenerator[Any, None]:
    from examples.in_memory.main import app

    async with LifespanManager(app) as manager:
        yield manager.app


@pytest.fixture(scope="session")
async def client(app: Any) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(app=app, base_url="http://localhost") as client:
        yield client
