from __future__ import annotations

import base64
import json
import time
from typing import Any

from agent_squad.types import ParticipantRole, TimestampedMessage

from .exceptions import MessageTooLargeError, UnknownMessageSchemaError

SCHEMA_VERSION = 1


def _to_json(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, list):
        return [_to_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json(item) for key, item in value.items()}
    return value


def _from_json(value: Any) -> Any:
    if isinstance(value, list):
        return [_from_json(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"$bytes"}:
            return base64.b64decode(value["$bytes"])
        return {key: _from_json(item) for key, item in value.items()}
    return value


def encode_message(
    message: Any,
    *,
    role: str,
    timestamp: int | None = None,
    max_bytes: int | None = None,
) -> bytes:
    payload = {
        "citations": _to_json(getattr(message, "citations", None)),
        "content": _to_json(message.content),
        "role": role,
        "timestamp": timestamp or getattr(message, "timestamp", None) or int(time.time() * 1000),
        "version": SCHEMA_VERSION,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    if max_bytes is not None and len(encoded) > max_bytes:
        raise MessageTooLargeError(
            f"Encoded message is {len(encoded)} bytes; configured limit is {max_bytes}"
        )
    return encoded


def decode_message(encoded: bytes) -> TimestampedMessage:
    payload = json.loads(encoded)
    if payload.get("version") != SCHEMA_VERSION:
        raise UnknownMessageSchemaError(f"Unsupported message schema {payload.get('version')!r}")
    message = TimestampedMessage(
        ParticipantRole(payload["role"]),
        _from_json(payload["content"]),
        timestamp=payload["timestamp"],
    )
    message.citations = _from_json(payload.get("citations"))
    return message
