
from dataclasses import FrozenInstanceError

import pytest

from agent_squad_aerospike import AerospikeConfig


def test_defaults_are_ce_compatible_and_bounded() -> None:
    config = AerospikeConfig()
    assert config.seeds == ("127.0.0.1:3000",)
    assert config.namespace == "test"
    assert len(config.conversation_set) <= 15
    assert len(config.directory_set) <= 15
    assert config.hard_history_limit == 1_000
    assert config.max_agents_per_session > 0
    assert config.membership_cache_capacity > 0
    assert config.ttl_seconds is None
    assert config.socket_timeout_ms < config.total_timeout_ms
    assert config.max_write_retries == 0


def test_configuration_is_immutable() -> None:
    config = AerospikeConfig()
    with pytest.raises(FrozenInstanceError):
        config.namespace = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seeds", ()),
        ("namespace", ""),
        ("conversation_set", "x" * 16),
        ("directory_set", "x" * 16),
        ("hard_history_limit", 0),
        ("hard_history_limit", 3),
        ("max_agents_per_session", 0),
        ("membership_cache_capacity", 0),
        ("socket_timeout_ms", 0),
        ("total_timeout_ms", 0),
        ("ttl_seconds", 0),
    ],
)
def test_invalid_bounds_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        AerospikeConfig(**{field: value})  # type: ignore[arg-type]


def test_positive_ttl_requires_safe_early_membership_refresh() -> None:
    assert AerospikeConfig(ttl_seconds=60, membership_refresh_seconds=45)
    with pytest.raises(ValueError):
        AerospikeConfig(ttl_seconds=60)
    with pytest.raises(ValueError):
        AerospikeConfig(ttl_seconds=60, membership_refresh_seconds=60)


def test_refresh_is_invalid_without_ttl() -> None:
    with pytest.raises(ValueError):
        AerospikeConfig(membership_refresh_seconds=30)


def test_effective_history_limit_rounds_down_and_honors_hard_cap() -> None:
    config = AerospikeConfig(hard_history_limit=10)
    assert config.effective_history_limit(None) == 10
    assert config.effective_history_limit(9) == 8
    assert config.effective_history_limit(20) == 10
    with pytest.raises(ValueError):
        config.effective_history_limit(1)


def test_optional_connectivity_settings_are_preserved() -> None:
    config = AerospikeConfig(
        seeds=("seed-a:3000", "seed-b:3000"),
        username="app",
        password="secret",
    )
    assert config.seeds == ("seed-a:3000", "seed-b:3000")
    assert config.username == "app"
    assert config.password == "secret"

