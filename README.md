# agent-squad-aerospike

Asynchronous Aerospike Community Edition-compatible chat storage for Agent Squad.

## Installation and compatibility

```shell
pip install agent-squad-aerospike
```

The initial release supports Python 3.11–3.14, Agent Squad `>=1.1.3,<1.2`, Aerospike Developer SDK `>=0.9.0a5,<0.10`, and Aerospike Database 6.0 or later. It requires only Community Edition database features.

## Usage

```python
from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig

config = AerospikeConfig(
    seeds=("db-a.example.com:3000", "db-b.example.com:3000"),
    namespace="test",
    hard_history_limit=1_000,
)

async with await AerospikeChatStorage.connect(config) as storage:
    orchestrator = AgentSquad(storage=storage)
```

`connect()` owns one long-lived Developer SDK client and closes it idempotently. To borrow an existing session, construct `AerospikeChatStorage(session, config)`; closing storage never closes that session.

`save_chat_message` and `save_chat_messages` follow the abstract Agent Squad boolean contract: confirmed mutations return `True`; empty batches and intentionally suppressed same-role single messages return `False`; invalid input, operational errors, oversized data, and ambiguous writes raise exceptions. Fetch history explicitly after a save when needed.

## Configuration

Defaults use seed `127.0.0.1:3000`, namespace `test`, sets `as_chats` and `as_agents`, a 1,000-message hard history cap, 256 KiB encoded-message limit, 8 MiB configured record limit, 1,000 agents per directory, and 10,000 process-local membership confirmations. The socket and total timeout defaults are 5 and 30 seconds. Non-idempotent writes use zero retries.

Adapter TTL is disabled by default, deferring to namespace policy. A positive `ttl_seconds` requires a positive `membership_refresh_seconds` strictly below the TTL. Credentials are optional runtime settings; never put secrets in source control.

## Data model and behavior

Each `(user_id, session_id, agent_id)` has one conversation record. Each `(user_id, session_id)` has one bounded directory record mapping agent IDs to ordering metadata. Domain-separated, length-prefixed identifier tuples are hashed into primary keys. Fixed sets, primary-key reads, and batch reads avoid scans and secondary indexes.

Conversation saves use one atomic server-side operation to check the persisted last role, append complete versioned messages, trim only oldest whole messages, update metadata, and apply optional sliding TTL. Caller limits can only lower the hard cap and odd limits round down. Complete content blocks, binary data, citations, Unicode, roles, and timestamps round-trip without truncation. Oversized messages raise `MessageTooLargeError`; server record overflow raises `ConversationTooLargeError`.

Directory registration happens before a conversation save when membership is unconfirmed. Confirmed memberships use a bounded LRU-style process cache, concurrent misses are coalesced, and positive-TTL confirmations refresh before directory expiry. Cache eviction or process restart safely repeats the idempotent registration. A failed registration is not cached. The two records are not transactionally coupled: readers tolerate a registered directory member whose conversation is absent. Directories are bounded; sharding is deferred to a separate change if measured contention requires it.

Same-role suppression is atomic. Non-idempotent appends are not blindly retried; an in-doubt response raises `AmbiguousWriteError` because retrying could duplicate a message. `fetch_all_chats` tolerates missing conversations, checks every batch result, orders by timestamp with deterministic tie-breaking, and prefixes assistant text with `[agent-id]` while preserving remaining content blocks.

For a runnable end-to-end example using only the installed packages, see [examples/basic_orchestration](examples/basic_orchestration).

## Community Edition development

```shell
docker compose up -d --wait
.venv/bin/pytest -m integration
```

The included server uses namespace `test`, persistent file-backed storage, ports 3000–3002, and `nsup-period 1` for TTL tests. Positive TTL writes require `nsup-period > 0`; `allow-ttl-without-nsup` is testing-only and is not used.

Aerospike is a smart client database. Applications must directly reach every advertised cluster node. Multiple seeds improve bootstrap resilience but are not a proxy data path; do not put a generic load balancer in front of seed hosts. Configure credentials and advertised or alternate addresses so every discovered node remains reachable.

TLS configuration, vector search and AVS, graph/AGS, TypeScript, Swift, multi-record transactions, durable deletes, rack awareness, and directory sharding are outside this package's scope.

## Benchmarking

The benchmark compares the production Aerospike adapter with Agent Squad's official DynamoDB adapter through their public chat-storage methods. It is an as-shipped integration comparison: Aerospike performs atomic server-side append and trim, while the DynamoDB adapter performs a whole-conversation read-modify-write. Correctness counters must be interpreted alongside latency and throughput.

Start the local Aerospike Community Edition and DynamoDB Local services, then run a small smoke profile using the sibling benchmark framework source:

```shell
docker compose up -d --wait
AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local \
PYTHONPATH=../ai-ecosystem-benchmark/src \
uv run --extra test --extra benchmark python benchmarks/agent_squad_workload.py \
  --key-pool-size 2 --agents-per-session 2 --history-size 4 \
  --payload-bytes 64 --qps 2 --max-in-flight 2 --duration-seconds 1 \
  --run-id local-smoke --output agent-squad-benchmark.json
```

Local results are always marked `environment: local` and `publishable: false`. DynamoDB Local does not reproduce managed DynamoDB networking, latency, durability, adaptive capacity, partitioning, retries, throttling, consumed capacity, or cost and must not be used for production database-performance claims. This benchmark does not provision or connect to managed services.

The JSON output records the workload seed and dimensions, client limits, component versions, response and service percentiles, achieved QPS, failures, correctness counters, environment classification, and adapter semantics. Use the same `--seed` but unique `--run-id` values to isolate repeated runs; reusing a run ID intentionally reuses prior records. Keep run parameters identical across backends and repeat QPS, history-size, payload-size, agent-count, distributed-key, and contention profiles on the same otherwise-idle host. Docker CPU and memory limits, host load, thermal throttling, filesystem performance, and background processes can affect results. Inspect the difference between response and service latency before attributing a ceiling to a database, and treat automatic client retries as part of observed latency.
