"""Toy example: Agent Squad orchestration with Aerospike-backed chat storage.

Runs entirely locally: two toy agents, a keyword classifier, and chat history
persisted to a local Aerospike Community Edition instance. No cloud credentials
or LLM calls required.

Usage:
    docker compose up -d aerospike
    pip install agent-squad-aerospike
    python examples/basic_orchestration/basic_orchestration.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from agent_squad.agents import Agent, AgentOptions
from agent_squad.classifiers import Classifier, ClassifierResult
from agent_squad.orchestrator import AgentSquad
from agent_squad.types import ConversationMessage, ParticipantRole

from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig

USER_ID = "toy-user"
SESSION_ID = f"toy-{uuid.uuid4().hex[:8]}"

MESSAGES = [
    "hello, echo this back to me",
    "please upper this line",
    "another echo please",
    "upper case me one more time",
]


class EchoAgent(Agent):
    """Repeats the user's message back."""

    async def process_request(
        self,
        input_text: str,
        user_id: str,
        session_id: str,
        chat_history: list[ConversationMessage],
        additional_params: dict[str, str] | None = None,
    ) -> ConversationMessage:
        return ConversationMessage(
            role=ParticipantRole.ASSISTANT,
            content=[{"text": f"echo: {input_text}"}],
        )


class UpperAgent(Agent):
    """Uppercases the user's message."""

    async def process_request(
        self,
        input_text: str,
        user_id: str,
        session_id: str,
        chat_history: list[ConversationMessage],
        additional_params: dict[str, str] | None = None,
    ) -> ConversationMessage:
        return ConversationMessage(
            role=ParticipantRole.ASSISTANT,
            content=[{"text": input_text.upper()}],
        )


class KeywordClassifier(Classifier):
    """Routes inputs containing "upper" to UpperAgent, everything else to EchoAgent."""

    async def process_request(
        self,
        input_text: str,
        chat_history: list[ConversationMessage],
    ) -> ClassifierResult:
        agent_id = "upper-agent" if "upper" in input_text.lower() else "echo-agent"
        return ClassifierResult(selected_agent=self.get_agent_by_id(agent_id), confidence=1.0)


def _text(message: ConversationMessage) -> str:
    if message.content and isinstance(message.content[0], dict):
        return str(message.content[0].get("text", ""))
    return str(message.content)


async def main() -> None:
    config = AerospikeConfig(seeds=("127.0.0.1:3000",), namespace="test")
    try:
        storage = await AerospikeChatStorage.connect(config)
    except Exception as exc:
        print(f"Could not connect to Aerospike at {config.seeds}: {exc}")
        print("Is the local server running? Try: docker compose up -d aerospike")
        sys.exit(1)

    async with storage:
        orchestrator = AgentSquad(storage=storage, classifier=KeywordClassifier())
        orchestrator.add_agent(
            EchoAgent(AgentOptions(name="Echo Agent", description="Repeats your message back."))
        )
        orchestrator.add_agent(
            UpperAgent(AgentOptions(name="Upper Agent", description="Uppercases your message."))
        )

        for text in MESSAGES:
            response = await orchestrator.route_request(text, USER_ID, SESSION_ID)
            print(f"user> {text}")
            print(f"agent> {_text(response.output)}\n")

        history = await storage.fetch_all_chats(USER_ID, SESSION_ID)
        print("--- merged history from Aerospike ---")
        for message in history:
            role = message.role.value if isinstance(message.role, ParticipantRole) else message.role
            print(f"{role}: {_text(message)}")


if __name__ == "__main__":
    asyncio.run(main())
