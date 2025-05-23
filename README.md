# fastapi-cache

[![pypi](https://img.shields.io/pypi/v/fastapi-cache2.svg?style=flat)](https://pypi.org/p/fastapi-cache2)
[![license](https://img.shields.io/github/license/long2ice/fastapi-cache)](https://github.com/long2ice/fastapi-cache/blob/main/LICENSE)
[![CI/CD](https://github.com/long2ice/fastapi-cache/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/long2ice/fastapi-cache/actions/workflows/ci-cd.yml)

## Introduction

`fastapi-cache` is a tool to cache FastAPI endpoint and function results, with
backends supporting Redis, Memcached, and Amazon DynamoDB.

## Features

- Supports `redis`, `memcache`, `dynamodb`, and `in-memory` backends.
- Easy integration with [FastAPI](https://fastapi.tiangolo.com/).
- Support for HTTP cache headers like `ETag` and `Cache-Control`, as well as conditional `If-Match-None` requests.
- Have an optional Cache Context available during function call, that can be acquired with `get_cache_ctx` function.

## Requirements

- FastAPI
- `redis` when using `RedisBackend`.
- `memcache` when using `MemcacheBackend`.
- `aiobotocore` when using `DynamoBackend`.

## Install

```shell
> pip install fastapi-cache2
```

or

```shell
> pip install "fastapi-cache2[redis]"
```

or

```shell
> pip install "fastapi-cache2[memcache]"
```

or

```shell
> pip install "fastapi-cache2[dynamodb]"
```

## Usage

### Quick Start

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache

from redis import asyncio as aioredis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    redis = aioredis.from_url("redis://localhost")
    FastAPICache.init(RedisBackend(redis), prefix="fastapi-cache")
    yield


app = FastAPI(lifespan=lifespan)


@cache()
async def get_cache():
    return 1


@app.get("/")
@cache(expire=60)
async def index():
    return dict(hello="world")
```

### Initialization

First you must call `FastAPICache.init` during startup FastAPI startup; this is where you set global configuration.

### Use the `@cache` decorator

If you want cache a FastAPI response transparently, you can use the `@cache`
decorator between the router decorator and the view function.

Parameter | type | default               | description
------------ | ----|-----------------------| --------
`expire` | `int` |                       | sets the caching time in seconds
`namespace` | `str` | `""`                  | namespace to use to store certain cache items
`coder` | `Coder` | `JsonCoder`           | which coder to use, e.g. `JsonCoder`
`key_builder` | `KeyBuilder` callable | `default_key_builder` | which key builder to use
`injected_dependency_namespace` | `str` | `__fastapi_cache`     | prefix for injected dependency keywords.
`cache_status_header` | `str` | `X-FastAPI-Cache`     | Name for the header on the response indicating if the request was served from cache; either `HIT` or `MISS`.
`with_lock` | `bool` | False                 | Whether to lock on cache get/set - may be useful to limit concurrent executions of heavy functions so that the first call could cache the function and subsequent calls will return the cached version
`lock_timeout` | `int` | 60                    | Timeout used when lock is enabled - function will be executed after timeout expires or when lock is released
`bypass_cache_control` | `bool` | False | Bypass "Cache-Control" headers from origin - may be useful to enforce caching

You can also use the `@cache` decorator on regular functions to cache their result.

Currently, lock is available only with `inmemory` and `redis` backends (other backends will just ignore it).

### Injected Request and Response dependencies

The `cache` decorator injects dependencies for the `Request` and `Response`
objects, so that it can add cache control headers to the outgoing response, and
return a 304 Not Modified response when the incoming request has a matching
`If-Non-Match` header. This only happens if the decorated endpoint doesn't already
list these dependencies already.

The keyword arguments for these extra dependencies are named
`__fastapi_cache_request` and `__fastapi_cache_response` to minimize collisions.
Use the `injected_dependency_namespace` argument to `@cache` to change the
prefix used if those names would clash anyway.


### Supported data types

When using the (default) `JsonCoder`, the cache can store any data type that FastAPI can convert to JSON, including Pydantic models and dataclasses,
_provided_ that your endpoint has a correct return type annotation. An
annotation is not needed if the return type is a standard JSON-supported Python
type such as a dictionary or a list.

E.g. for an endpoint that returns a Pydantic model named `SomeModel`, the return annotation is used to ensure that the cached result is converted back to the correct class:

```python
from .models import SomeModel, create_some_model

@app.get("/foo")
@cache(expire=60)
async def foo() -> SomeModel:
    return create_some_model()
```

It is not sufficient to configure a response model in the route decorator; the cache needs to know what the method itself returns. If no return type decorator is given, the primitive JSON type is returned instead.

For broader type support, use the `fastapi_cache.coder.PickleCoder` or implement a custom coder (see below).

### Custom coder

By default use `JsonCoder`, you can write custom coder to encode and decode cache result, just need
inherit `fastapi_cache.coder.Coder`.

```python
from typing import Any
import orjson
from fastapi.encoders import jsonable_encoder
from fastapi_cache import Coder

class ORJsonCoder(Coder):
    @classmethod
    def encode(cls, value: Any) -> bytes:
        return orjson.dumps(
            value,
            default=jsonable_encoder,
            option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY,
        )

    @classmethod
    def decode(cls, value: bytes) -> Any:
        return orjson.loads(value)


@app.get("/")
@cache(expire=60, coder=ORJsonCoder)
async def index():
    return dict(hello="world")
```

### Custom key builder

By default the `default_key_builder` builtin key builder is used; this creates a
cache key from the function module and name, and the positional and keyword
arguments converted to their `repr()` representations, encoded as a MD5 hash.
You can provide your own by passing a key builder in to `@cache()`, or to
`FastAPICache.init()` to apply globally.

For example, if you wanted to use the request method, URL and query string as a cache key instead of the function identifier you could use:

```python
def request_key_builder(
    func,
    namespace: str = "",
    *,
    request: Request = None,
    response: Response = None,
    *args,
    **kwargs,
):
    return ":".join([
        namespace,
        request.method.lower(),
        request.url.path,
        repr(sorted(request.query_params.items()))
    ])


@app.get("/")
@cache(expire=60, key_builder=request_key_builder)
async def index():
    return dict(hello="world")
```

### Cache Context

You can fetch current cache context with `get_cache_ctx` function. It returns a mutable mapping of type `CacheCtx` and has all caching parameters along with some variables set during cache initialisation.

This context can be used to override some caching variables if they depend on the function context:

```python
from fastapi_cache import FastAPICache, get_cache_ctx

@app.get("/")
@cache(namespace="test")
async def cache_with_ctx(new_expire: int):
    ctx = get_cache_ctx()

    # override expiration with the provided value
    ctx["expire"] = new_expire
    return {"result": 42}
```

### Using Locks with Cache

The `with_lock` parameter can be used to prevent multiple concurrent executions of computationally expensive functions. When enabled, if multiple requests try to access the same uncached endpoint simultaneously, only the first request will execute the function while others wait for the result to be cached. This is particularly useful for:

1. Preventing the "thundering herd" problem where multiple requests execute the same expensive operation simultaneously
2. Reducing database load by ensuring only one request computes a result
3. Improving response times for concurrent requests to uncached endpoints

Currently, lock functionality is available only with `inmemory` and `redis` backends.

Here's an example of using `with_lock` for a computationally expensive operation:

```python
import asyncio
import time
from fastapi import FastAPI
from fastapi_cache.decorator import cache

app = FastAPI()

@app.get("/expensive-operation")
@cache(namespace="heavy_computation", with_lock=True, lock_timeout=30)
async def expensive_operation():
    # Simulate a heavy computation
    print("Starting expensive operation...")

    # This could be a database query, ML model inference, or any heavy computation
    await asyncio.sleep(5)  # Simulating 5 seconds of processing

    result = {"data": "Expensive computation result", "timestamp": time.time()}
    print("Expensive operation completed")

    return result
```

In this example:
- `with_lock=True` ensures that if multiple concurrent requests hit this endpoint, only one will execute the function
- `lock_timeout=30` sets a maximum lock time of 30 seconds to prevent deadlocks
- After the first request completes, the result is cached and subsequent requests will get the cached result immediately

Without the lock, if 10 concurrent requests hit an uncached endpoint, all 10 would execute the expensive operation simultaneously. With the lock, only one request executes the operation while the other 9 wait for the result to be cached.

## Backend notes

### InMemoryBackend

The `InMemoryBackend` stores cache data in memory and only deletes when an
expired key is accessed. This means that if you don't access a function after
data has been cached, the data will not be removed automatically.

### RedisBackend

When using the Redis backend, please make sure you pass in a redis client that does [_not_ decode responses][redis-decode] (`decode_responses` **must** be `False`, which is the default). Cached data is stored as `bytes` (binary), decoding these in the Redis client would break caching.

[redis-decode]: https://redis-py.readthedocs.io/en/latest/examples/connection_examples.html#by-default-Redis-return-binary-responses,-to-decode-them-use-decode_responses=True

## Tests and coverage

```shell
coverage run -m pytest
coverage html
xdg-open htmlcov/index.html
```

## License

This project is licensed under the [Apache-2.0](https://github.com/long2ice/fastapi-cache/blob/master/LICENSE) License.
