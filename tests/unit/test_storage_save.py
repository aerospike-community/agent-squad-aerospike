from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from agent_squad.types import ConversationMessage, ParticipantRole

from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig


@pytest.fixture(autouse=True)
def registered_membership() -> object:
    with patch("agent_squad_aerospike.storage.register_membership", new=AsyncMock()):
        yield


async def test_single_message_save_is_atomic_and_returns_true() -> None:
    storage = AerospikeChatStorage(Mock(), AerospikeConfig())
    message = ConversationMessage(ParticipantRole.USER, [{"text": "hello"}])
    with patch(
        "agent_squad_aerospike.storage.atomic_append", new=AsyncMock(return_value=True)
    ) as op:
        assert await storage.save_chat_message("u", "s", "a", message)
    op.assert_awaited_once()
    assert op.await_args.kwargs["first_role"] == "user"
    assert op.await_args.kwargs["limit"] == 1_000
    assert op.await_args.args[2][0]["role"] == "user"


async def test_same_role_filter_returns_false() -> None:
    storage = AerospikeChatStorage(Mock())
    message = ConversationMessage(ParticipantRole.USER, [{"text": "again"}])
    with patch("agent_squad_aerospike.storage.atomic_append", new=AsyncMock(return_value=False)):
        assert not await storage.save_chat_message("u", "s", "a", message)


async def test_batch_validation_and_atomic_append() -> None:
    storage = AerospikeChatStorage(Mock())
    user = ConversationMessage(ParticipantRole.USER, [{"text": "hello"}])
    assistant = ConversationMessage(ParticipantRole.ASSISTANT, [{"text": "hi"}])
    with patch(
        "agent_squad_aerospike.storage.atomic_append", new=AsyncMock(return_value=True)
    ) as op:
        assert not await storage.save_chat_messages("u", "s", "a", [])
        assert await storage.save_chat_messages("u", "s", "a", [user, assistant])
    assert [entry["role"] for entry in op.await_args.args[2]] == ["user", "assistant"]

    with pytest.raises(ValueError, match="alternate"):
        await storage.save_chat_messages("u", "s", "a", [user, user])


async def test_effective_limit_and_ttl_reach_atomic_operation() -> None:
    config = AerospikeConfig(hard_history_limit=10, ttl_seconds=60, membership_refresh_seconds=45)
    storage = AerospikeChatStorage(Mock(), config)
    message = ConversationMessage(ParticipantRole.USER, [{"text": "hello"}])
    with patch(
        "agent_squad_aerospike.storage.atomic_append", new=AsyncMock(return_value=True)
    ) as op:
        await storage.save_chat_message("u", "s", "a", message, max_history_size=9)
    assert op.await_args.kwargs["limit"] == 8
    assert op.await_args.kwargs["ttl_seconds"] == 60
    assert op.await_args.kwargs["updated"] > 0


async def test_size_and_operational_failures_are_raised() -> None:
    storage = AerospikeChatStorage(Mock())
    message = ConversationMessage(ParticipantRole.USER, [{"text": "hello"}])
    with (
        patch(
            "agent_squad_aerospike.storage.atomic_append",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
        pytest.raises(RuntimeError, match="database unavailable"),
    ):
        await storage.save_chat_message("u", "s", "a", message)
    with pytest.raises(ValueError):
        await storage.save_chat_message("", "s", "a", message)
