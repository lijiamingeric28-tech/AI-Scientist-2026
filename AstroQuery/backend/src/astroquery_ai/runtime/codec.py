"""Canonical JSON used by the registry, runtime and export protocols."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(data: str | bytes) -> Any:
    def invalid(value: str):
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid)


def canonical(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def content_hash(value: dict) -> str:
    return digest({key: val for key, val in value.items() if key != "content_sha256"})


def decimal_literal(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value, flags=re.ASCII)
    ):
        raise ValueError("scientific number must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal string") from exc
    if not number.is_finite():
        raise ValueError("non-finite scientific number")
    return value
