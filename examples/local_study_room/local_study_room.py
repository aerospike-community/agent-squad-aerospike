"""Local Study Room: Ollama-backed agents with expiring Aerospike chat memory.

Two specialists — an Explainer and a Quizmaster — share a short-lived study
session persisted in Aerospike. Run it once, run it again with the same
session id to see restored context, then wait past the TTL and run again to
see the room start fresh.

Prerequisites:
    docker compose up -d aerospike          # Aerospike Community Edition
    ollama serve                            # Ollama daemon
    ollama pull llama3.2:1b                 # or set OLLAMA_MODEL

Usage:
    pip install "agent-squad-aerospike[examples]"
    python examples/local_study_room/local_study_room.py "explain TTL expiry"
    python examples/local_study_room/local_study_room.py --session room-1 "quiz me on that"
    python examples/local_study_room/local_study_room.py --session room-1 --inspect
"""


import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from agent_squad.agents import Agent, AgentOptions
from agent_squad.classifiers import Classifier, ClassifierResult
from agent_squad.orchestrator import AgentSquad
from agent_squad.types import ConversationMessage, ParticipantRole

from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig

DEFAULT_MODEL = "llama3.2:1b"
DEFAULT_TTL_SECONDS = 120

EXPLAINER_PROMPT = """You are the Explainer in a small study room about Aerospike and
distributed systems. Give concise, accurate explanations of a few short paragraphs.
If the conversation history is empty or unrelated to the question, say so and
answer from the question alone instead of pretending to remember earlier turns."""

QUIZMASTER_PROMPT = """You are the Quizmaster in a small study room. Ask one or two short
questions that check the learner's understanding of what was discussed earlier
in this session. If there is no earlier lesson in the conversation history,
say that you have nothing to quiz on and ask what topic they want to study."""

QUIZ_HINTS = ("quiz", "test me", "question", "check my understanding", "knowledge check")


class OllamaChat:
    """Thin async boundary over the optional ``ollama`` client package.

    The import is deferred so the example module and its tests load without
    the package installed.
    """

    def __init__(self, model: str, host: str | None = None) -> None:
        try:
            from ollama import AsyncClient
        except ImportError as exc:
            raise RuntimeError(
                "The 'ollama' package is required. "
                'Install it with: pip install "agent-squad-aerospike[examples]"'
            ) from exc
        self._client = AsyncClient(host=host)
        self._model = model

    async def complete(
        self,
        system_prompt: str,
        chat_history: list[ConversationMessage],
        input_text: str,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            *to_chat_messages(chat_history),
            {"role": "user", "content": input_text},
        ]
        response = await self._client.chat(model=self._model, messages=messages)
        content = response.message.content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"model {self._model!r} returned an empty response")
        return content


def _role_name(role: Any) -> str:
    return str(getattr(role, "value", role)).lower()


def message_text(message: ConversationMessage) -> str:
    """Extract the text of the first content block of a conversation message."""
    if message.content and isinstance(message.content[0], dict):
        return str(message.content[0].get("text", ""))
    return str(message.content or "")


def to_chat_messages(chat_history: list[ConversationMessage]) -> list[dict[str, str]]:
    """Convert Agent Squad history to Ollama/OpenAI-style chat messages."""
    messages = []
    for message in chat_history:
        role = _role_name(message.role)
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": message_text(message)})
    return messages


class OllamaAgent(Agent):
    """A study-room specialist that replies through a shared chat boundary.

    Agent Squad only passes the selected agent's own history to
    ``process_request``. ``history_source`` optionally overrides that with a
    merged view (e.g. ``storage.fetch_all_chats``) so a specialist can see the
    whole room's conversation.
    """

    def __init__(
        self,
        options: AgentOptions,
        chat: Any,
        system_prompt: str,
        history_source: Callable[[str, str], Awaitable[list[Any]]] | None = None,
    ) -> None:
        super().__init__(options)
        self._chat = chat
        self._system_prompt = system_prompt
        self._history_source = history_source

    async def process_request(
        self,
        input_text: str,
        user_id: str,
        session_id: str,
        chat_history: list[ConversationMessage],
        additional_params: dict[str, str] | None = None,
    ) -> ConversationMessage:
        if self._history_source is not None:
            chat_history = await self._history_source(user_id, session_id)
        reply = await self._chat.complete(self._system_prompt, chat_history, input_text)
        return ConversationMessage(
            role=ParticipantRole.ASSISTANT,
            content=[{"text": reply}],
        )


class StudyClassifier(Classifier):
    """Deterministic routing: quiz requests go to the Quizmaster."""

    async def process_request(
        self,
        input_text: str,
        chat_history: list[ConversationMessage],
    ) -> ClassifierResult:
        agent_id = (
            "quizmaster" if any(hint in input_text.lower() for hint in QUIZ_HINTS) else "explainer"
        )
        return ClassifierResult(selected_agent=self.get_agent_by_id(agent_id), confidence=1.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ollama-backed study room with expiring Aerospike chat memory.",
    )
    parser.add_argument("message", nargs="?", help="one user message to route")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="print stored history for the session without routing a message",
    )
    parser.add_argument("--user", default="local-user", help="user id (default: local-user)")
    parser.add_argument(
        "--session",
        default="study-room",
        help="session id; reuse it across runs to observe persistence (default: study-room)",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help=f"sliding TTL for chat records in seconds (default: {DEFAULT_TTL_SECONDS})",
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=None,
        help="membership refresh interval in seconds (default: half of --ttl)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
        help=f"Ollama model name (default: $OLLAMA_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--ollama-host",
        default=os.environ.get("OLLAMA_HOST"),
        help="Ollama base URL (default: $OLLAMA_HOST or the ollama client default)",
    )
    parser.add_argument(
        "--seed",
        default=os.environ.get("AEROSPIKE_SEED", "127.0.0.1:3000"),
        help="Aerospike seed host (default: $AEROSPIKE_SEED or 127.0.0.1:3000)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.refresh is None:
        args.refresh = max(1, args.ttl // 2)
    if args.ttl <= 0:
        parser.error("--ttl must be a positive number of seconds")
    if args.refresh <= 0 or args.refresh >= args.ttl:
        parser.error("--refresh must be positive and smaller than --ttl")
    if args.inspect and args.message:
        parser.error("use either a message or --inspect, not both")
    if not args.inspect and not args.message:
        parser.error("provide a message to route, or --inspect to read stored history")
    return args


async def print_history(storage: AerospikeChatStorage, user_id: str, session_id: str) -> int:
    history = await storage.fetch_all_chats(user_id, session_id)
    print(f"stored messages in session: {len(history)}")
    for message in history:
        print(f"  {_role_name(message.role)}> {message_text(message)}")
    if not history:
        print("  (empty — the room is fresh or its records have expired)")
    return len(history)


async def run(args: argparse.Namespace) -> int:
    config = AerospikeConfig(
        seeds=(args.seed,),
        namespace="test",
        ttl_seconds=args.ttl,
        membership_refresh_seconds=args.refresh,
    )
    try:
        storage = await AerospikeChatStorage.connect(config)
    except Exception as exc:
        print(f"Could not connect to Aerospike at {config.seeds}: {exc}")
        print("Is the local server running? Try: docker compose up -d aerospike")
        return 1

    async with storage:
        print(f"session={args.session} user={args.user} ttl={args.ttl}s")
        if args.inspect:
            await print_history(storage, args.user, args.session)
            return 0

        # Observe stored history before routing so the new turn does not
        # mask whether the room was restored or already expired.
        prior_count = await print_history(storage, args.user, args.session)

        chat = OllamaChat(model=args.model, host=args.ollama_host)
        orchestrator = AgentSquad(storage=storage, classifier=StudyClassifier())
        orchestrator.add_agent(
            OllamaAgent(
                AgentOptions(
                    name="Explainer",
                    description="Explains Aerospike and distributed-systems concepts.",
                ),
                chat=chat,
                system_prompt=EXPLAINER_PROMPT,
            )
        )
        orchestrator.add_agent(
            OllamaAgent(
                AgentOptions(
                    name="Quizmaster",
                    description="Quizzes the learner on this session's earlier discussion.",
                ),
                chat=chat,
                system_prompt=QUIZMASTER_PROMPT,
                history_source=storage.fetch_all_chats,
            )
        )

        try:
            response = await orchestrator.route_request(args.message, args.user, args.session)
        except Exception as exc:
            print(f"Ollama request failed: {exc}")
            print(f"Is Ollama running with {args.model!r}? Try: ollama pull {args.model}")
            return 1

        print(f"\nuser> {args.message}")
        print(f"{response.metadata.agent_name}> {message_text(response.output)}")
        if prior_count:
            print(f"\n(context restored from {prior_count} earlier stored message(s))")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
