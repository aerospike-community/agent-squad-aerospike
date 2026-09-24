
import importlib.util
import sys
from pathlib import Path

import pytest
from agent_squad.agents import AgentOptions
from agent_squad.types import ConversationMessage, ParticipantRole

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = PROJECT_ROOT / "examples" / "local_study_room" / "local_study_room.py"


def load_example():
    spec = importlib.util.spec_from_file_location("local_study_room", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["local_study_room"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def example():
    return load_example()


class FakeChat:
    def __init__(self, reply: str = "fake reply") -> None:
        self.reply = reply
        self.calls: list[tuple[str, list[dict[str, str]], str]] = []

    async def complete(
        self,
        system_prompt: str,
        chat_history: list[ConversationMessage],
        input_text: str,
    ) -> str:
        self.calls.append((system_prompt, chat_history, input_text))
        return self.reply


def _make_classifier(example) -> tuple[object, object]:
    chat = FakeChat()
    explainer = example.OllamaAgent(
        AgentOptions(name="Explainer", description="explains"),
        chat=chat,
        system_prompt="explain",
    )
    quizmaster = example.OllamaAgent(
        AgentOptions(name="Quizmaster", description="quizzes"),
        chat=chat,
        system_prompt="quiz",
    )
    classifier = example.StudyClassifier()
    classifier.set_agents({explainer.id: explainer, quizmaster.id: quizmaster})
    return classifier, chat


async def test_classifier_routes_teaching_to_explainer(example) -> None:
    classifier, _ = _make_classifier(example)
    result = await classifier.process_request("explain TTL expiry", [])
    assert result.selected_agent.id == "explainer"


async def test_classifier_routes_quiz_to_quizmaster(example) -> None:
    classifier, _ = _make_classifier(example)
    for prompt in ("quiz me on that", "test me please", "check my understanding"):
        result = await classifier.process_request(prompt, [])
        assert result.selected_agent.id == "quizmaster", prompt


async def test_ollama_agent_returns_conversation_message(example) -> None:
    chat = FakeChat(reply="an explanation")
    agent = example.OllamaAgent(
        AgentOptions(name="Explainer", description="explains"),
        chat=chat,
        system_prompt="explain",
    )
    response = await agent.process_request("why does ttl need nsup", "u", "s", [], None)
    assert response.role == ParticipantRole.ASSISTANT
    assert response.content == [{"text": "an explanation"}]
    system_prompt, history, user_input = chat.calls[0]
    assert system_prompt == "explain"
    assert history == []
    assert user_input == "why does ttl need nsup"


async def test_agent_uses_merged_history_source(example) -> None:
    merged = [
        ConversationMessage(
            role=ParticipantRole.ASSISTANT,
            content=[{"text": "[explainer] earlier lesson"}],
        )
    ]

    async def fetch_all(user_id: str, session_id: str):
        assert (user_id, session_id) == ("u", "s")
        return merged

    chat = FakeChat()
    agent = example.OllamaAgent(
        AgentOptions(name="Quizmaster", description="quizzes"),
        chat=chat,
        system_prompt="quiz",
        history_source=fetch_all,
    )
    await agent.process_request("quiz me", "u", "s", [], None)
    _, history, _ = chat.calls[0]
    assert history == merged


def test_to_chat_messages_maps_roles_and_text(example) -> None:
    history = [
        ConversationMessage(role=ParticipantRole.USER, content=[{"text": "teach me"}]),
        ConversationMessage(
            role=ParticipantRole.ASSISTANT,
            content=[{"text": "[explainer] here is the lesson"}],
        ),
    ]
    messages = example.to_chat_messages(history)
    assert messages == [
        {"role": "user", "content": "teach me"},
        {"role": "assistant", "content": "[explainer] here is the lesson"},
    ]


def test_parse_args_defaults(example) -> None:
    args = example.parse_args(["hello"])
    assert args.user == "local-user"
    assert args.session == "study-room"
    assert args.ttl == example.DEFAULT_TTL_SECONDS
    assert args.refresh == args.ttl // 2
    assert args.model == example.DEFAULT_MODEL


def test_parse_args_requires_refresh_below_ttl(example) -> None:
    with pytest.raises(SystemExit):
        example.parse_args(["hi", "--ttl", "60", "--refresh", "60"])


def test_parse_args_requires_message_or_inspect(example) -> None:
    with pytest.raises(SystemExit):
        example.parse_args([])


def test_parse_args_rejects_message_with_inspect(example) -> None:
    with pytest.raises(SystemExit):
        example.parse_args(["hello", "--inspect"])
