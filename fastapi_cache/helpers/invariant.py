from typing import TypeVar

from msgspec import UnsetType

T = TypeVar("T")


def invariant(val: T | UnsetType, default: T) -> T:
    return val if not isinstance(val, UnsetType) else default
