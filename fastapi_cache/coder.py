import datetime
import pickle
from collections.abc import Callable
from decimal import Decimal
from functools import partial
from typing import (
    Any,
    TypeVar,
    overload,
)

import msgspec
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response
from starlette.templating import (
    _TemplateResponse as TemplateResponse,  # pyright: ignore[reportPrivateUsage]
)

from fastapi_cache.helpers.typing import is_subclass_safe

T = TypeVar("T")


CONVERTERS: dict[str, Callable[[Any], Any]] = {
    "date": partial(msgspec.convert, type=datetime.date),
    "datetime": partial(msgspec.convert, type=datetime.datetime),
    "decimal": partial(msgspec.convert, type=Decimal),
}


def dec_hook(type_: type[T], obj: Any) -> T:
    if is_subclass_safe(type_, BaseModel):
        if isinstance(obj, bytes):
            return type_.model_validate_json(obj)  # type: ignore[no-any-return, attr-defined]
        return type_.model_validate(obj)  # type: ignore[no-any-return, attr-defined]
    raise NotImplementedError


def enc_hook(obj: Any) -> Any:
    try:
        return jsonable_encoder(obj)
    except ValueError as e:
        raise NotImplementedError from e


def object_hook(obj: dict[str, Any]) -> Any:
    if not (_spec_type := obj.get("_spec_type")):
        return obj

    if _spec_type in CONVERTERS:
        return CONVERTERS[_spec_type](obj["val"])
    raise TypeError(f"Unknown {_spec_type}")


class Coder:
    @classmethod
    def encode(cls, value: Any) -> bytes:
        raise NotImplementedError

    @classmethod
    def decode(cls, value: bytes) -> Any:
        raise NotImplementedError

    @overload
    @classmethod
    def decode_as_type(cls, value: bytes, *, type_: type[T]) -> T: ...

    @overload
    @classmethod
    def decode_as_type(cls, value: bytes, *, type_: None) -> Any: ...

    @classmethod
    def decode_as_type(cls, value: bytes, *, type_: type[T] | None) -> T | Any:
        raise NotImplementedError


class JsonCoder(Coder):
    @classmethod
    def encode(cls, value: Any) -> bytes:
        if isinstance(value, JSONResponse):
            return value.body if isinstance(value.body, bytes) else bytes(value.body)
        if isinstance(value, datetime.datetime):
            to_encode = {"val": str(value), "_spec_type": "datetime"}
        elif isinstance(value, datetime.date):
            to_encode = {"val": str(value), "_spec_type": "date"}
        elif isinstance(value, Decimal):
            to_encode = {"val": str(value), "_spec_type": "decimal"}
        else:
            to_encode = value
        return msgspec.json.encode(to_encode, enc_hook=enc_hook)

    @classmethod
    def decode(cls, value: bytes) -> Any:
        # explicitly decode from UTF-8 bytes first, as otherwise
        # json.loads() will first have to detect the correct UTF-
        # encoding used.
        decoded_value = msgspec.json.decode(value)
        if isinstance(decoded_value, dict):
            return object_hook(decoded_value)  # pyright: ignore[reportUnknownArgumentType]
        return decoded_value

    @classmethod
    def decode_as_type(cls, value: bytes, *, type_: type[T] | None) -> T | Any:
        if type_ and is_subclass_safe(type_, Response):
            return Response(value)
        result = cls.decode(value)
        if type_ is not None:
            return msgspec.convert(result, strict=False, dec_hook=dec_hook, type=type_)
        return result


class PickleCoder(Coder):
    @classmethod
    def encode(cls, value: Any) -> bytes:
        if isinstance(value, TemplateResponse):
            value = value.body
        return pickle.dumps(value)

    @classmethod
    def decode(cls, value: bytes) -> Any:
        return pickle.loads(value)  # noqa: S301

    @classmethod
    def decode_as_type(cls, value: bytes, *, type_: type[T] | None) -> T | Any:
        value = cls.decode(value)
        if type_ is not None and not isinstance(value, type_):
            return msgspec.convert(value, type=type_, strict=False)
        return value
