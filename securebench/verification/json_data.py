"""Canonical finite-JSON encoding and strict decoding for trusted protocols."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from securebench.data_formats import strict_json_loads as strict_json_loads


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


def json_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
