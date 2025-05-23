# pyright: reportGeneralTypeIssues=false
import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pendulum
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import redis.asyncio as redis
from fastapi_cache import FastAPICache, get_cache_ctx
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.coder import PickleCoder
from fastapi_cache.decorator import cache
from redis.asyncio.connection import ConnectionPool


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    pool = ConnectionPool.from_url(url="redis://localhost")
    r = redis.Redis(connection_pool=pool)
    FastAPICache.init(RedisBackend(r), prefix="fastapi-cache")
    yield


app = FastAPI(lifespan=lifespan)

app.mount(
    path="/static",
    app=StaticFiles(directory="./"),
    name="static",
)
templates = Jinja2Templates(directory="./")
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
async def get_data(request: Request, response: Response):
    return pendulum.today()


# Note: This function MUST be sync to demonstrate fastapi-cache's correct handling,
# i.e. running cached sync functions in threadpool just like FastAPI itself!
@app.get("/blocking")
@cache(namespace="test", expire=10)  # pyright: ignore[reportArgumentType]
def blocking():
    time.sleep(2)
    return {"ret": 42}


@app.get("/datetime")
@cache(namespace="test", expire=2)
async def get_datetime(request: Request, response: Response):
    print(request, response)
    return pendulum.now()


@app.get("/html", response_class=HTMLResponse)
@cache(expire=60, namespace="html", coder=PickleCoder)
async def cache_html(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "ret": await get_ret()})


@app.get("/with_lock")
@cache(namespace="test", with_lock=True)
async def cache_with_lock():
    print("lock acquired")
    await asyncio.sleep(3)
    return {"result": 42}


@app.get("/with_ctx")
@cache(namespace="test")
async def cache_with_ctx():
    ctx = get_cache_ctx()

    ctx.expire = 300
    return {"result": 42}


@app.get("/cache_response_obj")
@cache(namespace="test", expire=5)
async def cache_response_obj():
    return JSONResponse({"a": 1})


if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)
