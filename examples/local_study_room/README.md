# Local study room example

`local_study_room.py` demonstrates a **real local LLM** (Ollama) driving two Agent
Squad specialists — an **Explainer** and a **Quizmaster** — whose shared
conversation memory lives in `AerospikeChatStorage` and **expires via TTL** when
the room goes idle.

Unlike `basic_orchestration`, this example performs real model inference and
shows three storage behaviors the deterministic example cannot:

- history **restored across process restarts** (same `--session` id);
- history **shared across agents** (the Quizmaster sees the Explainer's lesson);
- history **expiring after inactivity** (sliding TTL + Aerospike NSUP).

## Prerequisites

```shell
docker compose up -d aerospike        # Aerospike Community Edition (repo root)
ollama serve                          # start the Ollama daemon
ollama pull llama3.2:1b               # the default model (~1.3 GB, one-time download)
pip install "agent-squad-aerospike[examples]"
```

The model is never downloaded implicitly — pull it yourself, or pick another
instruct model with `--model` / `OLLAMA_MODEL`.

## The walkthrough

All commands use the same `--session` id so records accumulate in one room.

### 1. First turn — teach

```shell
python examples/local_study_room/local_study_room.py \
  --session room-1 "explain why read-modify-write loses updates in Aerospike"
```

The Explainer calls Ollama and the user/assistant pair is written to Aerospike
with a 120-second TTL (default; override with `--ttl`).

### 2. Second turn — cross-agent context

```shell
python examples/local_study_room/local_study_room.py \
  --session room-1 "quiz me on that"
```

The deterministic classifier routes this to the Quizmaster, which receives the
merged session history — including the Explainer's earlier lesson — and quizzes
you on it. Before routing, the script prints the stored history so you can see
what was restored.

### 3. Sliding TTL while active

Every successful save refreshes the retention horizon. If you keep sending
messages within each TTL window, the room stays alive; each turn resets the
clock rather than expiring 120 seconds after creation.

### 4. Expiration after inactivity

Wait a little longer than the TTL (NSUP runs on a periodic cycle, so cleanup is
asynchronous — allow a few extra seconds) and inspect the room:

```shell
sleep 130
python examples/local_study_room/local_study_room.py --session room-1 --inspect
```

The stored history is empty. A follow-up message now starts a fresh room with
no memory of the earlier lesson — even though the session id is unchanged.

## How TTL works here

- `AerospikeConfig(ttl_seconds=..., membership_refresh_seconds=...)` sets a
  sliding TTL: each successful conversation write re-arms the record's expiry,
  and membership registration refreshes the session-directory record before it
  can expire (the refresh interval must be positive and smaller than the TTL —
  the script defaults it to half of `--ttl`).
- Expiry itself is performed by NSUP, Aerospike's namespace supervisor, which
  runs periodically — not exactly at void-time. The repo's
  `docker/aerospike.conf` sets `nsup-period 1` on the `test` namespace, which is
  required for positive TTL writes and works on Community Edition.
- The example never calls a cleanup, touch, scan, or delete API itself.

## Options

```
--session ID       session id; reuse across runs (default: study-room)
--user ID          user id (default: local-user)
--inspect          print stored history for the session, then exit
--ttl SECONDS      sliding TTL per record (default: 120)
--refresh SECONDS  membership refresh interval (default: half of --ttl)
--model NAME       Ollama model (default: $OLLAMA_MODEL or llama3.2:1b)
--ollama-host URL  Ollama base URL (default: $OLLAMA_HOST)
--seed HOST:PORT   Aerospike seed (default: $AEROSPIKE_SEED or 127.0.0.1:3000)
```
