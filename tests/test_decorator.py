import asyncio
from unittest import mock

import pendulum
from fastapi.routing import serialize_response
from httpx import AsyncClient

from fastapi_cache import FastAPICache
from fastapi_cache.decorator import MAX_AGE_NEVER_EXPIRES


async def test_datetime(client: AsyncClient) -> None:
    response = await client.get("/datetime")
    assert response.headers.get("X-FastAPI-Cache") == "MISS"
    now = response.json().get("now")
    now_ = pendulum.now().replace(microsecond=0)
    assert pendulum.parse(now).replace(microsecond=0) == now_  # type: ignore[union-attr, call-arg]
    response = await client.get("/datetime")
    assert response.headers.get("X-FastAPI-Cache") == "HIT"
    now = response.json().get("now")
    assert pendulum.parse(now).replace(microsecond=0) == now_  # type: ignore[union-attr, call-arg]
    await asyncio.sleep(3)
    response = await client.get("/datetime")
    now = response.json().get("now")
    assert response.headers.get("X-FastAPI-Cache") == "MISS"
    now = pendulum.parse(now).replace(microsecond=0)  # type: ignore[union-attr, call-arg]
    assert now != now_
    assert now == pendulum.now().replace(microsecond=0)


async def test_date(client: AsyncClient) -> None:
    """Test path function without request or response arguments."""
    response = await client.get("/date")
    assert response.headers.get("X-FastAPI-Cache") == "MISS"
    assert pendulum.parse(response.json()) == pendulum.today()

    # do it again to test cache
    response = await client.get("/date")
    assert response.headers.get("X-FastAPI-Cache") == "HIT"
    assert pendulum.parse(response.json()) == pendulum.today()

    # now test with cache disabled, as that's a separate code path
    FastAPICache._enable = False  # pyright: ignore[reportPrivateUsage]
    response = await client.get("/date")
    assert "X-FastAPI-Cache" not in response.headers
    assert pendulum.parse(response.json()) == pendulum.today()
    FastAPICache._enable = True  # pyright: ignore[reportPrivateUsage]


async def test_sync(client: AsyncClient) -> None:
    """Ensure that sync function support works."""
    response = await client.get("/sync-me")
    assert response.json() == 42


async def test_cache_response_obj(client: AsyncClient) -> None:
    with mock.patch("fastapi.routing.serialize_response", side_effect=serialize_response) as m:
        cache_response = await client.get("cache_response_obj")
        assert cache_response.json() == {"a": 1}
        assert cache_response.headers.get("cache-control")
        assert m.call_count == 0
        get_cache_response = await client.get("cache_response_obj")
        assert get_cache_response.json() == {"a": 1}
        assert get_cache_response.headers.get("cache-control")
        assert get_cache_response.headers.get("etag")
        assert m.call_count == 1


async def test_cache_response_obj_typed(client: AsyncClient) -> None:
    with mock.patch("fastapi.routing.serialize_response", side_effect=serialize_response) as m:
        cache_response = await client.get("cache_response_obj_typed")
        assert cache_response.json() == {"a": 1}
        assert cache_response.headers.get("cache-control")
        assert m.call_count == 0
        get_cache_response = await client.get("cache_response_obj_typed")
        assert get_cache_response.json() == {"a": 1}
        assert get_cache_response.headers.get("cache-control")
        assert get_cache_response.headers.get("etag")
        assert m.call_count == 0


async def test_kwargs(client: AsyncClient) -> None:
    name = "Jon"
    response = await client.get("/kwargs", params={"name": name})
    assert "X-FastAPI-Cache" not in response.headers
    assert response.json() == {"name": name}


async def test_method(client: AsyncClient) -> None:
    response = await client.get("/method")
    assert response.json() == 17


async def test_pydantic_model(client: AsyncClient) -> None:
    r1 = await client.get("/pydantic_instance")
    assert r1.headers.get("X-FastAPI-Cache") == "MISS"
    r2 = await client.get("/pydantic_instance")
    assert r2.headers.get("X-FastAPI-Cache") == "HIT"
    assert r1.json() == r2.json()


async def test_non_get(client: AsyncClient) -> None:
    response = await client.put("/uncached_put")
    assert "X-FastAPI-Cache" not in response.headers
    assert response.json() == {"value": 1}
    response = await client.put("/uncached_put")
    assert "X-FastAPI-Cache" not in response.headers
    assert response.json() == {"value": 2}


async def test_alternate_injected_namespace(client: AsyncClient) -> None:
    response = await client.get("/namespaced_injection")
    assert response.headers.get("X-FastAPI-Cache") == "MISS"
    assert response.json() == {"__fastapi_cache_request": 42, "__fastapi_cache_response": 17}


async def test_cache_control(client: AsyncClient) -> None:
    response = await client.get("/cached_put")
    assert response.json() == {"value": 1}

    # HIT
    response = await client.get("/cached_put")
    assert response.json() == {"value": 1}

    # no-cache
    response = await client.get("/cached_put", headers={"Cache-Control": "no-cache"})
    assert response.json() == {"value": 2}

    response = await client.get("/cached_put")
    assert response.json() == {"value": 2}

    # no-store
    response = await client.get("/cached_put", headers={"Cache-Control": "no-store"})
    assert response.json() == {"value": 3}

    response = await client.get("/cached_put")
    assert response.json() == {"value": 2}

    # bypass
    response = await client.get("/cached_with_bypass")
    assert response.json() == {"value": 1}

    # HIT, bypass Cache-Control
    response = await client.get("/cached_with_bypass", headers={"Cache-Control": "no-cache"})
    assert response.json() == {"value": 1}


async def test_lock(client: AsyncClient) -> None:
    responses = await asyncio.gather(
        client.get("/cached_with_lock"),
        client.get("/cached_with_lock"),
        client.get("/cached_with_lock"),
    )
    for response in responses:
        assert response.json() == {"value": 1}

    response = await client.get("/cached_with_lock", headers={"Cache-Control": "no-cache"})
    assert response.json() == {"value": 2}


async def test_ctx(client: AsyncClient) -> None:
    response = await client.get("/cached_with_ctx", params={"update_expire": 1})
    assert response.headers.get("cache-control") == "max-age=3600"
    assert response.json() == {"value": 1}
    response = await client.get("/cached_with_ctx", params={"update_expire": 1})
    assert response.headers.get("X-FastAPI-Cache") == "HIT"
    assert response.json() == {"value": 1}

    # ensure that global ctx remains
    response = await client.get("/cached_with_ctx", params={"update_expire": 0})
    assert response.json() == {"value": 2}
    assert response.headers.get("cache-control") == f"max-age={MAX_AGE_NEVER_EXPIRES}"


async def test_response_caching(client: AsyncClient) -> None:
    pass
