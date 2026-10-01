# Examples

## `basic_orchestration/`

A self-contained deterministic toy showing how an end user wires `agent-squad`
orchestration to `AerospikeChatStorage`. It defines two local agents (echo and
uppercase), a keyword classifier, routes scripted messages through
`AgentSquad.route_request`, and prints the merged history read back from
Aerospike.

Requires only the installed packages — no model, no credentials, no LLM calls.

```shell
docker compose up -d aerospike   # from the repository root
pip install agent-squad-aerospike
python examples/basic_orchestration/basic_orchestration.py
```

## `local_study_room/`

A local-LLM study room: Ollama-powered **Explainer** and **Quizmaster** agents
share Aerospike-backed session memory that **expires via sliding TTL** when
idle. Reuse a `--session` id across runs to watch context persist, transfer
between agents, and disappear after inactivity.

Requires Ollama and a pulled model — still localhost-only, no cloud credentials.

```shell
docker compose up -d aerospike
ollama pull llama3.2:1b
pip install "agent-squad-aerospike[examples]"
python examples/local_study_room/local_study_room.py --session room-1 "explain TTL expiry"
```

See `local_study_room/README.md` for the full persistence/expiration walkthrough.
