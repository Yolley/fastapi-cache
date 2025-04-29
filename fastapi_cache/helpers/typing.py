import inspect
from typing import Any


def is_subclass_safe(value: Any, classinfo: type) -> bool:
    return inspect.isclass(value) and issubclass(value, classinfo)
