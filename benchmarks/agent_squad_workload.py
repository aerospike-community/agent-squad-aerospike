"""Agent Squad chat-storage benchmark workload."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import random
import time
from dataclasses import asdict, dataclass
from itertools import count
from pathlib import Path
from typing import Any

from agent_squad.types import ConversationMessage, ParticipantRole
from ai_ecosystem_benchmark import BaseBenchmarkWorkload, BenchmarkRunner, DynamoDBConfig

from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig


@dataclass(frozen=True, slots=True)
class WorkloadConfig:
    seed: int = 20260915
    payload_bytes: int = 256
    history_size: int = 10
    agents_per_session: int = 4
    key_pool_size: int = 1024
    qps: int = 100
    max_in_flight: int = 256
    warmup_seconds: int = 1
    duration_seconds: int = 30
    ttl_seconds: int | None = None
    run_id: str = "default"

    def __post_init__(self) -> None:
        positive = {
            "payload_bytes": self.payload_bytes,
            "history_size": self.history_size,
            "agents_per_session": self.agents_per_session,
            "key_pool_size": self.key_pool_size,
            "qps": self.qps,
            "max_in_flight": self.max_in_flight,
            "duration_seconds": self.duration_seconds,
        }
        if any(value <= 0 for value in positive.values()):
            raise ValueError("workload dimensions must be positive")
        if self.history_size % 2:
            raise ValueError("history_size must be even")
        if self.warmup_seconds < 0:
            raise ValueError("warmup_seconds must not be negative")


@dataclass(slots=True)
class CorrectnessCounters:
    attempted: int = 0
    accepted: int = 0
    rejected: int = 0
    failed: int = 0
    missing: int = 0
    duplicate: int = 0
    out_of_order: int = 0
    incorrectly_attributed: int = 0
    ambiguous: int = 0


def payload(seed: int, index: int, size: int) -> str:
    prefix = f"{seed}:{index}:"
    if len(prefix.encode()) > size:
        raise ValueError("payload size is too small for deterministic prefix")
    return prefix + "x" * (size - len(prefix.encode()))


def message(seed: int, index: int, size: int) -> ConversationMessage:
    role = ParticipantRole.USER if index % 2 == 0 else ParticipantRole.ASSISTANT
    return ConversationMessage(role, [{"text": payload(seed, index, size)}])


def operation_sequence(seed: int, count_: int) -> list[str]:
    choices = ("append", "append", "append", "append", "fetch", "fetch", "fetch", "fetch_all")
    generator = random.Random(seed)
    return [generator.choice(choices) for _ in range(count_)]


def validate_outcomes(
    attempted_payloads: list[str],
    persisted_messages: list[Any],
    *,
    accepted: int,
    expected_agent_prefixes: set[str] | None = None,
) -> CorrectnessCounters:
    persisted = [_message_text(item) for item in persisted_messages]
    attempted = set(attempted_payloads)
    persisted_attempts = [item for item in persisted if item in attempted]
    counters = CorrectnessCounters(attempted=len(attempted_payloads), accepted=accepted)
    counters.missing = max(0, accepted - len(set(persisted_attempts)))
    counters.duplicate = len(persisted_attempts) - len(set(persisted_attempts))
    counters.out_of_order = sum(
        left.role == right.role
        for left, right in zip(persisted_messages, persisted_messages[1:], strict=False)
    )
    if expected_agent_prefixes is not None:
        observed = {
            text.split("]", 1)[0].removeprefix("[")
            for text in persisted
            if text.startswith("[") and "]" in text
        }
        counters.incorrectly_attributed = len(expected_agent_prefixes - observed)
    return counters


def _message_text(item: Any) -> str:
    content = item.content
    if isinstance(content, list) and content and isinstance(content[0], dict):
        return str(content[0].get("text", ""))
    return str(content)


class AgentSquadChatWorkload(BaseBenchmarkWorkload):
    def __init__(
        self,
        config: WorkloadConfig,
        *,
        aerospike_seed: str | None,
        dynamodb_config: DynamoDBConfig | None,
        aerospike_storage: Any | None = None,
        dynamodb_storage: Any | None = None,
    ) -> None:
        super().__init__(
            aerospike_connection_string=aerospike_seed,
            dynamodb_config=dynamodb_config,
        )
        self.config = config
        self._aerospike_storage = aerospike_storage
        self._dynamodb_storage = dynamodb_storage
        self._counter = count()
        self._mixed = operation_sequence(
            config.seed, max(10_000, config.qps * config.duration_seconds)
        )
        self.correctness: dict[str, CorrectnessCounters] = {
            "aerospike": CorrectnessCounters(),
            "dynamodb": CorrectnessCounters(),
        }
        self._contended_payloads: dict[str, list[str]] = {"aerospike": [], "dynamodb": []}
        self._contended_accepted = {"aerospike": 0, "dynamodb": 0}

    async def setup(self) -> None:
        if self.is_aerospike_enabled() and self._aerospike_storage is None:
            assert self.aerospike_connection_string is not None
            refresh = None
            if self.config.ttl_seconds is not None:
                refresh = max(1, self.config.ttl_seconds // 2)
            self._aerospike_storage = await AerospikeChatStorage.connect(
                AerospikeConfig(
                    seeds=(self.aerospike_connection_string,),
                    hard_history_limit=max(1_000, self.config.history_size),
                    ttl_seconds=self.config.ttl_seconds,
                    membership_refresh_seconds=refresh,
                )
            )
        if self.is_dynamodb_enabled() and self._dynamodb_storage is None:
            from agent_squad.storage import DynamoDbChatStorage

            assert self.dynamodb_config is not None
            ttl_key = "TTL" if self.config.ttl_seconds is not None else None
            self._dynamodb_storage = DynamoDbChatStorage(
                table_name=self.dynamodb_config.table_name,
                region=self.dynamodb_config.region,
                ttl_key=ttl_key,
                ttl_duration=self.config.ttl_seconds or 3600,
            )
            import boto3

            resource = boto3.resource(
                "dynamodb",
                region_name=self.dynamodb_config.region,
                endpoint_url=self.dynamodb_config.endpoint_url,
            )
            self._dynamodb_storage.dynamodb = resource
            self._dynamodb_storage.table = resource.Table(self.dynamodb_config.table_name)
        await self._seed_reads()
        if self.config.warmup_seconds:
            await asyncio.sleep(0)

    async def between_benchmarks(self) -> None:
        await asyncio.sleep(0)

    async def teardown(self) -> None:
        await self.validate_correctness()
        if self._aerospike_storage is not None:
            await self._aerospike_storage.close()

    async def validate_correctness(self) -> None:
        for backend, storage in (
            ("aerospike", self._aerospike_storage),
            ("dynamodb", self._dynamodb_storage),
        ):
            if storage is None or not self._contended_payloads[backend]:
                continue
            persisted = await storage.fetch_chat(
                self._user(0), f"{self.config.run_id}-contended", self._agent(0)
            )
            measured = validate_outcomes(
                self._contended_payloads[backend],
                persisted,
                accepted=self._contended_accepted[backend],
            )
            self.correctness[backend].missing = measured.missing
            self.correctness[backend].duplicate = measured.duplicate
            self.correctness[backend].out_of_order = measured.out_of_order

    def benchmark_metadata(self) -> dict[str, object]:
        versions = {}
        for package in ("agent-squad", "agent-squad-aerospike", "ai-ecosystem-benchmark"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "source"
        return {
            **super().benchmark_metadata(),
            "comparison": "local as-shipped integration",
            "publishable": False,
            "environment": "local",
            "dynamodb_local_limitations": (
                "does not reproduce managed networking, partitioning, durability, adaptive "
                "capacity, throttling, consumed capacity, or service-side latency"
            ),
            "workload": asdict(self.config),
            "correctness": {
                backend: asdict(counters) for backend, counters in self.correctness.items()
            },
            "versions": versions,
            "adapter_semantics": {
                "aerospike": "atomic server-side append and trim",
                "dynamodb": "whole-conversation read-modify-write",
            },
        }

    async def aerospike_append_one(self) -> None:
        await self._append_one("aerospike", self._aerospike_storage)

    async def dynamodb_append_one(self) -> None:
        await self._append_one("dynamodb", self._dynamodb_storage)

    async def aerospike_append_pair(self) -> None:
        await self._append_pair("aerospike", self._aerospike_storage)

    async def dynamodb_append_pair(self) -> None:
        await self._append_pair("dynamodb", self._dynamodb_storage)

    async def aerospike_fetch(self) -> None:
        await self._fetch(self._aerospike_storage)

    async def dynamodb_fetch(self) -> None:
        await self._fetch(self._dynamodb_storage)

    async def aerospike_fetch_all(self) -> None:
        await self._fetch_all(self._aerospike_storage)

    async def dynamodb_fetch_all(self) -> None:
        await self._fetch_all(self._dynamodb_storage)

    async def aerospike_mixed(self) -> None:
        await self._mixed_call("aerospike", self._aerospike_storage)

    async def dynamodb_mixed(self) -> None:
        await self._mixed_call("dynamodb", self._dynamodb_storage)

    async def aerospike_contended(self) -> None:
        await self._contended("aerospike", self._aerospike_storage)

    async def dynamodb_contended(self) -> None:
        await self._contended("dynamodb", self._dynamodb_storage)

    async def _seed_reads(self) -> None:
        for storage in (self._aerospike_storage, self._dynamodb_storage):
            if storage is None:
                continue
            for key_index in range(self.config.key_pool_size):
                for agent_index in range(self.config.agents_per_session):
                    await storage.save_chat_messages(
                        self._user(key_index),
                        self._session(key_index),
                        self._agent(agent_index),
                        [
                            message(self.config.seed, index, self.config.payload_bytes)
                            for index in range(self.config.history_size)
                        ],
                        self.config.history_size,
                    )

    async def _append_one(self, backend: str, storage: Any) -> None:
        index = next(self._counter)
        counters = self.correctness[backend]
        counters.attempted += 1
        try:
            saved = await storage.save_chat_message(
                self._user(index),
                f"{self.config.run_id}-append-{index}",
                self._agent(0),
                message(self.config.seed, index * 2, self.config.payload_bytes),
                self.config.history_size,
            )
            if saved is False:
                counters.rejected += 1
            else:
                counters.accepted += 1
        except Exception:
            counters.failed += 1
            raise

    async def _append_pair(self, backend: str, storage: Any) -> None:
        index = next(self._counter)
        await storage.save_chat_messages(
            self._user(index),
            f"{self.config.run_id}-pair-{index}",
            self._agent(0),
            [
                message(self.config.seed, index * 2, self.config.payload_bytes),
                message(self.config.seed, index * 2 + 1, self.config.payload_bytes),
            ],
            self.config.history_size,
        )
        self.correctness[backend].attempted += 1
        self.correctness[backend].accepted += 1

    async def _fetch(self, storage: Any) -> None:
        index = next(self._counter) % self.config.key_pool_size
        await storage.fetch_chat(
            self._user(index),
            self._session(index),
            self._agent(index % self.config.agents_per_session),
        )

    async def _fetch_all(self, storage: Any) -> None:
        index = next(self._counter) % self.config.key_pool_size
        await storage.fetch_all_chats(self._user(index), self._session(index))

    async def _mixed_call(self, backend: str, storage: Any) -> None:
        index = next(self._counter)
        operation = self._mixed[index % len(self._mixed)]
        if operation == "append":
            await self._append_one(backend, storage)
        elif operation == "fetch":
            await self._fetch(storage)
        else:
            await self._fetch_all(storage)

    async def _contended(self, backend: str, storage: Any) -> None:
        counters = self.correctness[backend]
        index = next(self._counter) * 2
        contended_message = message(self.config.seed, index, self.config.payload_bytes)
        self._contended_payloads[backend].append(_message_text(contended_message))
        counters.attempted += 1
        saved = await storage.save_chat_message(
            self._user(0),
            f"{self.config.run_id}-contended",
            self._agent(0),
            contended_message,
            self.config.history_size,
        )
        if saved is False:
            counters.rejected += 1
        else:
            counters.accepted += 1
            self._contended_accepted[backend] += 1

    def _user(self, index: int) -> str:
        return f"bench-{self.config.run_id}-user-{index}"

    def _session(self, index: int) -> str:
        return f"bench-{self.config.run_id}-session-{index}"

    @staticmethod
    def _agent(index: int) -> str:
        return f"agent-{index}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Agent Squad chat storage backends")
    parser.add_argument("--aerospike-seed", default="127.0.0.1:3000")
    parser.add_argument("--dynamodb-region", default="us-east-1")
    parser.add_argument("--dynamodb-table", default="agent-squad-benchmark")
    parser.add_argument("--dynamodb-endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--run-id", default=str(int(time.time())))
    parser.add_argument("--payload-bytes", type=int, default=256)
    parser.add_argument("--history-size", type=int, default=10)
    parser.add_argument("--agents-per-session", type=int, default=4)
    parser.add_argument("--key-pool-size", type=int, default=1024)
    parser.add_argument("--qps", type=int, default=100)
    parser.add_argument("--max-in-flight", type=int, default=256)
    parser.add_argument("--warmup-seconds", type=int, default=1)
    parser.add_argument("--duration-seconds", type=int, default=30)
    parser.add_argument("--ttl-seconds", type=int)
    parser.add_argument("--output", type=Path, default=Path("agent-squad-benchmark.json"))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    config = WorkloadConfig(
        seed=args.seed,
        payload_bytes=args.payload_bytes,
        history_size=args.history_size,
        agents_per_session=args.agents_per_session,
        key_pool_size=args.key_pool_size,
        qps=args.qps,
        max_in_flight=args.max_in_flight,
        warmup_seconds=args.warmup_seconds,
        duration_seconds=args.duration_seconds,
        ttl_seconds=args.ttl_seconds,
        run_id=args.run_id,
    )
    dynamodb = (
        None
        if args.dynamodb_endpoint.lower() == "none"
        else DynamoDBConfig(
            region=args.dynamodb_region,
            table_name=args.dynamodb_table,
            endpoint_url=args.dynamodb_endpoint,
        )
    )
    workload = AgentSquadChatWorkload(
        config,
        aerospike_seed=args.aerospike_seed or None,
        dynamodb_config=dynamodb,
    )
    runner = BenchmarkRunner(
        queries_per_second=config.qps,
        scheduler_thread_count=1,
        worker_thread_count=config.max_in_flight,
        runtime_per_function=config.duration_seconds,
        workload=workload,
    )
    runner.run()
    runner.print_metrics()
    runner.write_json(args.output)
    print(json.dumps({"results": str(args.output)}, indent=2))
