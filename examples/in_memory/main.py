# pyright: reportGeneralTypeIssues=false
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pendulum
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fastapi_cache import FastAPICache, get_cache_ctx
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    FastAPICache.init(InMemoryBackend())
    yield


app = FastAPI(lifespan=lifespan)

ret = 0


@cache(namespace="test", expire=1)
async def get_ret():
    global ret
    ret = ret + 1
    return ret


@app.get("/")
@cache(namespace="test", expire=10)
async def index():
    return {"ret": await get_ret()}


@app.get("/clear")
async def clear():
    return await FastAPICache.clear(namespace="test")


@app.get("/date")
@cache(namespace="test", expire=10)
async def get_date():
    return pendulum.today()


@app.get("/datetime")
@cache(namespace="test", expire=2)
async def get_datetime(request: Request, response: Response):
    return {"now": pendulum.now()}


@cache(namespace="test")
async def func_kwargs(*unused_args, **kwargs):
    return kwargs


@app.get("/kwargs")
async def get_kwargs(name: str):
    return await func_kwargs(name, name=name)


@app.get("/sync-me")
@cache(namespace="test")  # pyright: ignore[reportArgumentType]
def sync_me():
    # as per the fastapi docs, this sync function is wrapped in a thread,
    # thereby converted to async. fastapi-cache does the same.
    return 42


@app.get("/cache_response_obj")
@cache(namespace="test", expire=5)
async def cache_response_obj():
    return JSONResponse({"a": 1})


@app.get("/cache_response_obj_typed")
@cache(namespace="test", expire=5)
async def cache_response_obj_typed() -> JSONResponse:
    return JSONResponse({"a": 1})


class SomeClass:
    def __init__(self, value):
        self.value = value

    async def handler_method(self):
        return self.value


# register an instance method as a handler
instance = SomeClass(17)
app.get("/method")(cache(namespace="test")(instance.handler_method))


# cache a Pydantic model instance; the return type annotation is required in this case
class Item(BaseModel):
    name: str
    description: str | None = None
    price: float
    tax: float | None = None


@app.get("/pydantic_instance")
@cache(namespace="test", expire=5)
async def pydantic_instance() -> Item:
    return Item(name="Something", description="An instance of a Pydantic model", price=10.5)


put_ret = 0


@app.put("/uncached_put")
@cache(namespace="test", expire=5)
async def uncached_put():
    global put_ret
    put_ret = put_ret + 1
    return {"value": put_ret}


put_ret2 = 0


@app.get("/cached_put")
@cache(namespace="test", expire=5)
async def cached_put():
    global put_ret2
    put_ret2 = put_ret2 + 1
    return {"value": put_ret2}


put_ret3 = 0


@app.get("/cached_with_bypass")
@cache(namespace="test", expire=5, bypass_cache_control=True)
async def cached_with_bypass():
    global put_ret3
    put_ret3 = put_ret3 + 1
    return {"value": put_ret3}


put_ret4 = 0


@app.get("/cached_with_lock")
@cache(namespace="test", with_lock=True, lock_timeout=3)
async def cached_with_lock():
    global put_ret4
    put_ret4 = put_ret4 + 1
    await asyncio.sleep(1)
    return {"value": put_ret4}


put_ret5 = 0


@app.get("/cached_with_ctx")
@cache(namespace="test")
async def cached_with_ctx(update_expire: bool = True):
    global put_ret5

    ctx = get_cache_ctx()
    if update_expire:
        ctx.expire = 3_600
    put_ret5 = put_ret5 + 1
    return {"value": put_ret5}


@app.get("/namespaced_injection")
@cache(namespace="test", expire=5, injected_dependency_namespace="monty_python")  # pyright: ignore[reportArgumentType]
def namespaced_injection(__fastapi_cache_request: int = 42, __fastapi_cache_response: int = 17) -> dict[str, int]:
    return {
        "__fastapi_cache_request": __fastapi_cache_request,
        "__fastapi_cache_response": __fastapi_cache_response,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)
