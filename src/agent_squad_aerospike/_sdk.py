from __future__ import annotations

import json
from typing import Any

from aerospike_async import ResultCode
from aerospike_sdk import AerospikeError

from .exceptions import AmbiguousWriteError, ConversationTooLargeError, DirectoryFullError


def map_write_failure(result: Any) -> bool:
    if result.in_doubt:
        raise AmbiguousWriteError("The write outcome is unknown") from result.exception
    if result.result_code == ResultCode.FILTERED_OUT:
        return False
    if result.result_code == ResultCode.RECORD_TOO_BIG:
        raise ConversationTooLargeError("The resulting conversation record is too large")
    if result.exception is not None:
        raise result.exception
    raise RuntimeError(f"Aerospike write failed with result code {result.result_code}")


def inspect_batch_results(results: list[Any]) -> list[Any]:
    successful = []
    for result in results:
        if result.result_code == ResultCode.OK:
            successful.append(result)
        elif result.result_code != ResultCode.KEY_NOT_FOUND_ERROR:
            if result.exception is not None:
                raise result.exception
            raise RuntimeError(f"Aerospike batch item failed with result code {result.result_code}")
    return successful


async def register_membership(
    session: Any,
    key: Any,
    agent_id: str,
    *,
    updated: int,
    max_agents: int,
    ttl_seconds: int | None,
) -> None:
    quoted_agent = json.dumps(agent_id, ensure_ascii=False)
    expression = (
        "not($.agents.exists()) "
        f"or $.agents.{quoted_agent}.exists() "
        f"or $.agents.{{}}.count() < {max_agents}"
    )
    operation = (
        session.upsert(key)
        .where(expression)
        .fail_on_filtered_out()
        .bin("agents")
        .map_upsert_items({agent_id: updated})
        .bin("updated")
        .set_to(updated)
    )
    operation = (
        operation.expire_record_after_seconds(ttl_seconds)
        if ttl_seconds is not None
        else operation.with_no_change_in_expiration()
    )
    try:
        stream = await operation.execute()
        await stream.first_or_raise()
    except AerospikeError as exc:
        if exc.result_code == ResultCode.FILTERED_OUT:
            raise DirectoryFullError("The session agent directory is full") from exc
        raise


async def atomic_append(
    session: Any,
    key: Any,
    messages: list[dict[str, Any]],
    *,
    first_role: str,
    limit: int,
    updated: int,
    ttl_seconds: int | None,
) -> bool:
    expression = (
        f'not($.msgs.exists()) or $.msgs.[].count() == 0 or $.msgs.[-1].role != "{first_role}"'
    )
    operation = (
        session.upsert(key)
        .where(expression)
        .fail_on_filtered_out()
        .bin("msgs")
        .list_append_items(messages)
        .bin("msgs")
        .list_trim(-limit, limit)
        .bin("updated")
        .set_to(updated)
        .bin("schema")
        .set_to(1)
    )
    operation = (
        operation.expire_record_after_seconds(ttl_seconds)
        if ttl_seconds is not None
        else operation.with_no_change_in_expiration()
    )
    try:
        stream = await operation.execute()
        await stream.first_or_raise()
    except AerospikeError as exc:
        if exc.in_doubt:
            raise AmbiguousWriteError("The write outcome is unknown") from exc
        if exc.result_code == ResultCode.FILTERED_OUT:
            return False
        if exc.result_code == ResultCode.RECORD_TOO_BIG:
            raise ConversationTooLargeError(
                "The resulting conversation record is too large"
            ) from exc
        raise
    return True
