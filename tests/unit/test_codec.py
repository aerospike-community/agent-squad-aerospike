
import json

import pytest
from agent_squad.types import ConversationMessage, ParticipantRole, TimestampedMessage

from agent_squad_aerospike import UnknownMessageSchemaError
from agent_squad_aerospike._codec import decode_message, encode_message


def test_known_message_encoding_is_versioned_and_canonical() -> None:
    message = ConversationMessage(
        role=ParticipantRole.USER,
        content=[
            {"text": "héllo"},
            {"toolUse": {"input": {"raw": b"\x00\xff"}, "name": "lookup"}},
            {"image": {"format": "png", "source": None}},
        ],
        citations=[{"url": "https://example.com", "start": 0}],
    )
    encoded = encode_message(message, role="user", timestamp=123)
    assert json.loads(encoded) == {
        "citations": [{"start": 0, "url": "https://example.com"}],
        "content": [
            {"text": "héllo"},
            {"toolUse": {"input": {"raw": {"$bytes": "AP8="}}, "name": "lookup"}},
            {"image": {"format": "png", "source": None}},
        ],
        "role": "user",
        "timestamp": 123,
        "version": 1,
    }

    decoded = decode_message(encoded)
    assert decoded.role == ParticipantRole.USER
    assert decoded.content == message.content
    assert decoded.citations == message.citations
    assert decoded.timestamp == 123


def test_missing_content_and_timestamped_message_round_trip() -> None:
    message = TimestampedMessage(ParticipantRole.ASSISTANT, None, timestamp=456)
    message.citations = None
    decoded = decode_message(encode_message(message, role="assistant"))
    assert decoded.role == ParticipantRole.ASSISTANT
    assert decoded.content is None
    assert decoded.citations is None
    assert decoded.timestamp == 456


def test_unknown_schema_version_is_rejected() -> None:
    encoded = json.dumps(
        {"version": 99, "role": "user", "content": None, "citations": None, "timestamp": 1}
    ).encode()
    with pytest.raises(UnknownMessageSchemaError):
        decode_message(encoded)


def test_encode_message_has_no_client_side_size_limit() -> None:
    # No max_bytes parameter exists: encode_message never rejects a message for size.
    # Oversized conversations are rejected by the Aerospike server, not the client.
    message = ConversationMessage(ParticipantRole.USER, [{"text": "too large"}])
    encoded = encode_message(message, role="user", timestamp=1)
    assert json.loads(encoded)["content"] == [{"text": "too large"}]
