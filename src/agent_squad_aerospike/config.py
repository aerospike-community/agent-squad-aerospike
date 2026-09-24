
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AerospikeConfig:
    seeds: tuple[str, ...] = ("127.0.0.1:3000",)
    namespace: str = "test"
    conversation_set: str = "as_chats"
    directory_set: str = "as_agents"
    hard_history_limit: int = 1_000
    max_agents_per_session: int = 1_000
    membership_cache_capacity: int = 10_000
    ttl_seconds: int | None = None
    membership_refresh_seconds: int | None = None
    socket_timeout_ms: int = 5_000
    total_timeout_ms: int = 30_000
    max_write_retries: int = 0
    username: str | None = None
    password: str | None = None

    def __post_init__(self) -> None:
        if not self.seeds or any(not seed for seed in self.seeds):
            raise ValueError("at least one non-empty seed is required")
        if not self.namespace:
            raise ValueError("namespace must not be empty")
        if not self.conversation_set or len(self.conversation_set.encode()) > 15:
            raise ValueError("conversation_set must be 1-15 UTF-8 bytes")
        if not self.directory_set or len(self.directory_set.encode()) > 15:
            raise ValueError("directory_set must be 1-15 UTF-8 bytes")
        if self.hard_history_limit < 2 or self.hard_history_limit % 2:
            raise ValueError("hard_history_limit must be a positive even value")
        positive = {
            "max_agents_per_session": self.max_agents_per_session,
            "membership_cache_capacity": self.membership_cache_capacity,
            "socket_timeout_ms": self.socket_timeout_ms,
            "total_timeout_ms": self.total_timeout_ms,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.socket_timeout_ms > self.total_timeout_ms:
            raise ValueError("socket_timeout_ms must not exceed total_timeout_ms")
        if self.max_write_retries < 0:
            raise ValueError("max_write_retries must not be negative")
        if (self.username is None) != (self.password is None):
            raise ValueError("username and password must be configured together")
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if self.ttl_seconds is None and self.membership_refresh_seconds is not None:
            raise ValueError("membership refresh requires a positive TTL")
        if self.ttl_seconds is not None and (
            self.membership_refresh_seconds is None
            or self.membership_refresh_seconds <= 0
            or self.membership_refresh_seconds >= self.ttl_seconds
        ):
            raise ValueError("membership refresh must be positive and safely earlier than TTL")

    def effective_history_limit(self, requested: int | None) -> int:
        if requested is None:
            return self.hard_history_limit
        if requested < 2:
            raise ValueError("max_history_size must be at least 2")
        return min(self.hard_history_limit, requested - requested % 2)
