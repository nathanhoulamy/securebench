"""Canonical finite-JSON encoding and strict decoding for trusted protocols."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Encode finite JSON deterministically or raise ``TypeError``/``ValueError``."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except RecursionError as exc:
        raise ValueError("JSON data exceeds the nesting limit") from exc


def strict_json_loads(value: str | bytes) -> Any:
    """Decode one finite JSON value while rejecting duplicate object keys."""

    def reject_constant(constant: str) -> Any:
        raise ValueError(f"non-finite JSON number: {constant}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = item
        return result

    try:
        return json.loads(
            value,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except RecursionError as exc:
        raise ValueError("JSON data exceeds the nesting limit") from exc


def json_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
