from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from agent_squad.types import ConversationMessage, ParticipantRole

from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig, DirectoryFullError


def message() -> ConversationMessage:
    return ConversationMessage(ParticipantRole.USER, [])


async def test_registration_precedes_conversation_and_caches_only_success() -> None:
    storage = AerospikeChatStorage(Mock())
    events: list[str] = []
    registration = AsyncMock(side_effect=lambda *args, **kwargs: events.append("directory"))
    append = AsyncMock(side_effect=lambda *args, **kwargs: events.append("conversation") or True)
    with (
        patch("agent_squad_aerospike.storage.register_membership", registration),
        patch("agent_squad_aerospike.storage.atomic_append", append),
    ):
        assert await storage.save_chat_message("u", "s", "a", message())
        assert events == ["directory", "conversation"]
        assert await storage.save_chat_message("u", "s", "a", message())
    registration.assert_awaited_once()

    failing = AerospikeChatStorage(Mock())
    with (
        patch(
            "agent_squad_aerospike.storage.register_membership",
            AsyncMock(side_effect=RuntimeError("failed")),
        ) as failed_registration,
        patch("agent_squad_aerospike.storage.atomic_append", AsyncMock()) as failed_append,
    ):
        for _ in range(2):
            with pytest.raises(RuntimeError, match="failed"):
                await failing.save_chat_message("u", "s", "a", message())
    assert failed_registration.await_count == 2
    failed_append.assert_not_awaited()


async def test_concurrent_misses_are_single_flight() -> None:
    storage = AerospikeChatStorage(Mock())

    async def slow_registration(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(0.01)

    with (
        patch(
            "agent_squad_aerospike.storage.register_membership",
            AsyncMock(side_effect=slow_registration),
        ) as register,
        patch("agent_squad_aerospike.storage.atomic_append", AsyncMock(return_value=True)),
    ):
        await asyncio.gather(
            *(storage.save_chat_message("u", "s", "a", message()) for _ in range(10))
        )
    register.assert_awaited_once()


async def test_cache_eviction_and_ttl_refresh_are_safe() -> None:
    now = [0.0]
    config = AerospikeConfig(
        membership_cache_capacity=1,
        ttl_seconds=60,
        membership_refresh_seconds=45,
    )
    storage = AerospikeChatStorage(Mock(), config, clock=lambda: now[0])
    with (
        patch("agent_squad_aerospike.storage.register_membership", AsyncMock()) as register,
        patch("agent_squad_aerospike.storage.atomic_append", AsyncMock(return_value=True)),
    ):
        await storage.save_chat_message("u", "s", "a", message())
        await storage.save_chat_message("u", "s", "b", message())
        await storage.save_chat_message("u", "s", "a", message())
        now[0] = 46
        await storage.save_chat_message("u", "s", "a", message())
    assert register.await_count == 4


async def test_directory_overflow_prevents_conversation_creation() -> None:
    storage = AerospikeChatStorage(Mock())
    with (
        patch(
            "agent_squad_aerospike.storage.register_membership",
            AsyncMock(side_effect=DirectoryFullError("full")),
        ),
        patch("agent_squad_aerospike.storage.atomic_append", AsyncMock()) as append,
        pytest.raises(DirectoryFullError),
    ):
        await storage.save_chat_message("u", "s", "new", message())
    append.assert_not_awaited()
