"""JSON (de)serialization for dataclass entities, enums, and datetimes."""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")
_UNION_TYPES = (typing.Union, types.UnionType)


def _default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    raise TypeError(f"Cannot serialize {type(obj)}")


def to_json(entity: Any) -> str:
    if dataclasses.is_dataclass(entity):
        data = dataclasses.asdict(entity)
    else:
        data = entity
    return json.dumps(data, default=_default)


def from_json(json_str: str, cls: type[T]) -> T:
    """Reconstruct a dataclass from stored JSON. Enum and datetime fields are
    coerced back based on the dataclass's type hints."""
    raw = json.loads(json_str)
    return _coerce(raw, cls)


def _coerce(raw: dict, cls: type[T]) -> T:
    # get_type_hints resolves string annotations (from __future__ import annotations)
    # back into real types, which dataclasses.fields(...).type does not.
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for key, value in raw.items():
        if key in hints:
            kwargs[key] = _coerce_value(value, hints.get(key))
    return cls(**kwargs)


def _unwrap_optional(hint: Any) -> Any:
    # Handles both `Optional[X]` / `typing.Union[X, None]` and the PEP 604
    # `X | None` syntax, which produces types.UnionType, not typing.Union.
    origin = typing.get_origin(hint)
    if origin in _UNION_TYPES:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return hint


def _coerce_value(value: Any, hint: Any) -> Any:
    if value is None or hint is None:
        return value
    hint = _unwrap_optional(hint)

    if dataclasses.is_dataclass(hint) and isinstance(value, dict):
        return _coerce(value, hint)

    if isinstance(hint, type) and issubclass(hint, Enum):
        return hint(value)

    if hint is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)

    origin = typing.get_origin(hint)
    if origin in (list, list) and isinstance(value, list):
        (item_hint,) = typing.get_args(hint) or (None,)
        return [_coerce_value(v, item_hint) for v in value]

    return value
