from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from aerospike_async import ResultCode
from agent_squad.types import ConversationMessage, ParticipantRole

from agent_squad_aerospike import AerospikeChatStorage
from agent_squad_aerospike._codec import encode_message


class Stream:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def first(self) -> object | None:
        return self.rows[0] if self.rows else None

    def __aiter__(self):  # type: ignore[no-untyped-def]
        async def rows():  # type: ignore[no-untyped-def]
            for row in self.rows:
                yield row

        return rows()


class Query:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    async def execute(self, *args: object, **kwargs: object) -> Stream:
        return Stream(self.rows)


def row(bins: dict[str, object] | None = None, *, code: object = ResultCode.OK) -> object:
    record = None if bins is None else SimpleNamespace(bins=bins)
    return SimpleNamespace(
        result_code=code,
        record=record,
        exception=None,
        record_or_raise=lambda: record,
    )


def entry(role: ParticipantRole, text: str, timestamp: int) -> dict[str, object]:
    message = ConversationMessage(role, [{"text": text}])
    return {
        "role": role.value,
        "timestamp": timestamp,
        "payload": encode_message(message, role=role.value, timestamp=timestamp),
    }


async def test_fetch_chat_handles_missing_and_applies_read_only_even_limit() -> None:
    session = Mock()
    session.query.side_effect = [
        Query([row(code=ResultCode.KEY_NOT_FOUND_ERROR)]),
        Query([row({"msgs": [entry(ParticipantRole.USER, str(i), i) for i in range(6)]})]),
    ]
    storage = AerospikeChatStorage(session)
    assert await storage.fetch_chat("u", "s", "a") == []
    messages = await storage.fetch_chat("u", "s", "a", max_history_size=3)
    assert [message.content for message in messages] == [[{"text": "4"}], [{"text": "5"}]]


async def test_fetch_all_chats_batches_orders_attributes_and_tolerates_missing() -> None:
    directory = row({"agents": {"b": 2, "a": 1, "missing": 3}})
    conversations = [
        row({"msgs": [entry(ParticipantRole.ASSISTANT, "from b", 10)]}),
        row({"msgs": [entry(ParticipantRole.USER, "from a", 10)]}),
        row(code=ResultCode.KEY_NOT_FOUND_ERROR),
    ]
    session = Mock()
    session.query.side_effect = [Query([directory]), Query(conversations)]
    storage = AerospikeChatStorage(session)
    messages = await storage.fetch_all_chats("u", "s")
    assert [message.content for message in messages] == [
        [{"text": "from a"}],
        [{"text": "[b] from b"}],
    ]
    assert session.query.call_count == 2
    assert len(session.query.call_args.args) == 3


async def test_fetch_all_chats_surfaces_per_key_failures() -> None:
    failed = row(code=ResultCode.TIMEOUT)
    failed.exception = RuntimeError("batch failed")
    session = Mock()
    session.query.side_effect = [Query([row({"agents": {"a": 1}})]), Query([failed])]
    storage = AerospikeChatStorage(session)
    with pytest.raises(RuntimeError, match="batch failed"):
        await storage.fetch_all_chats("u", "s")
