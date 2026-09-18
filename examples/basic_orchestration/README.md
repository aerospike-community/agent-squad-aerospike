# Basic orchestration example

`basic_orchestration.py` is a self-contained toy showing how an end user wires `agent-squad` orchestration to `AerospikeChatStorage`. It defines two local agents (echo and uppercase), a keyword classifier, routes scripted messages through `AgentSquad.route_request`, and prints the merged history read back from Aerospike via `fetch_all_chats`.

Requires only the installed packages — no cloud credentials, no LLM calls.

```shell
docker compose up -d aerospike   # from the repository root
pip install agent-squad-aerospike
python examples/basic_orchestration/basic_orchestration.py
```

Each run uses a fresh session id, so output is deterministic and history does not accumulate between runs.
