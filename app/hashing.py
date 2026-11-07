"""Deterministic SHA-256 payload hashing for loop detection."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _fallback_serializer(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=repr)
    if isinstance(obj, (bytes, bytearray)):
        return bytes(obj).decode("utf-8", errors="replace")
    return repr(obj)


def canonicalize(payload: Any) -> str:
    """Return a deterministic JSON string representation of *payload*."""
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_fallback_serializer,
        )
    except RecursionError:
        # FIX: Catch deeply nested payloads before they crash the worker
        raise ValueError("Payload is too deeply nested to be processed.")


def payload_hash(payload: Any) -> str:
    """Compute the SHA-256 hex digest of a canonicalized payload."""
    canonical = canonicalize(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()