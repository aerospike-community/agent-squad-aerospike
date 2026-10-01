
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2] / "ai-ecosystem-benchmark" / "src"))

from ai_ecosystem_benchmark import DynamoDBConfig  # noqa: E402

from benchmarks.agent_squad_workload import (  # noqa: E402
    AgentSquadChatWorkload,
    WorkloadConfig,
    message,
    operation_sequence,
    payload,
    validate_outcomes,
)


class FakeStorage:
    def __init__(self) -> None:
        self.chats: dict[tuple[str, str, str], list[Any]] = {}
        self.closed = False

    async def save_chat_message(
        self,
        user_id: str,
        session_id: str,
        agent_id: str,
        new_message: Any,
        max_history_size: int | None = None,
    ) -> bool:
        key = (user_id, session_id, agent_id)
        values = self.chats.setdefault(key, [])
        if values and values[-1].role == new_message.role:
            return False
        values.append(new_message)
        self.chats[key] = values[-(max_history_size or len(values)) :]
        return True

    async def save_chat_messages(
        self,
        user_id: str,
        session_id: str,
        agent_id: str,
        new_messages: list[Any],
        max_history_size: int | None = None,
    ) -> bool:
        for item in new_messages:
            saved = await self.save_chat_message(
                user_id, session_id, agent_id, item, max_history_size
            )
            if not saved:
                raise ValueError("roles must alternate")
        return True

    async def fetch_chat(self, user_id: str, session_id: str, agent_id: str) -> list[Any]:
        return list(self.chats.get((user_id, session_id, agent_id), []))

    async def fetch_all_chats(self, user_id: str, session_id: str) -> list[Any]:
        return [
            item
            for (stored_user, stored_session, _), values in self.chats.items()
            if stored_user == user_id and stored_session == session_id
            for item in values
        ]

    async def close(self) -> None:
        self.closed = True


def test_generators_are_deterministic_and_exact_sized() -> None:
    assert len(payload(42, 3, 32).encode()) == 32
    assert message(42, 0, 32).role.value == "user"
    assert message(42, 1, 32).role.value == "assistant"
    assert operation_sequence(42, 20) == operation_sequence(42, 20)


def test_final_state_validation_detects_lost_success_and_duplicates() -> None:
    persisted = [message(42, 0, 32), message(42, 0, 32)]
    text = payload(42, 0, 32)

    result = validate_outcomes([text, payload(42, 2, 32)], persisted, accepted=2)

    assert result.missing == 1
    assert result.duplicate == 1
    assert result.out_of_order == 1


@pytest.mark.asyncio
async def test_setup_seeds_identical_histories_and_public_scenarios() -> None:
    aerospike = FakeStorage()
    dynamodb = FakeStorage()
    config = WorkloadConfig(
        payload_bytes=32,
        history_size=4,
        agents_per_session=2,
        key_pool_size=2,
        warmup_seconds=0,
        duration_seconds=1,
        run_id="test",
    )
    workload = AgentSquadChatWorkload(
        config,
        aerospike_seed="127.0.0.1:3000",
        dynamodb_config=DynamoDBConfig(
            region="us-east-1", table_name="bench", endpoint_url="http://localhost:8000"
        ),
        aerospike_storage=aerospike,
        dynamodb_storage=dynamodb,
    )

    await workload.setup()

    assert aerospike.chats.keys() == dynamodb.chats.keys()
    for key in aerospike.chats:
        assert [(item.role, item.content) for item in aerospike.chats[key]] == [
            (item.role, item.content) for item in dynamodb.chats[key]
        ]
    assert all(len(history) == 4 for history in aerospike.chats.values())
    await workload.aerospike_append_one()
    await workload.dynamodb_append_pair()
    await workload.aerospike_fetch()
    await workload.dynamodb_fetch_all()
    await workload.aerospike_mixed()
    await workload.dynamodb_contended()
    metadata = workload.benchmark_metadata()
    assert metadata["comparison"] == "local as-shipped integration"
    assert metadata["publishable"] is False
    assert metadata["environment"] == "local"
    assert "managed networking" in metadata["dynamodb_local_limitations"]
    assert metadata["adapter_semantics"] == {
        "aerospike": "atomic server-side append and trim",
        "dynamodb": "whole-conversation read-modify-write",
    }
