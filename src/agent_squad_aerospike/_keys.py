
from hashlib import sha256


def _key(domain: str, parts: tuple[str, ...]) -> str:
    canonical = domain.encode() + b"\0"
    for part in parts:
        encoded = part.encode()
        canonical += len(encoded).to_bytes(4, "big") + encoded
    return sha256(canonical).hexdigest()


def conversation_key(user_id: str, session_id: str, agent_id: str) -> str:
    return _key("conversation", (user_id, session_id, agent_id))


def directory_key(user_id: str, session_id: str) -> str:
    return _key("directory", (user_id, session_id))
