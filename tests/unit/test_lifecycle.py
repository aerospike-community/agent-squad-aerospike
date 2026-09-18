from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from agent_squad_aerospike import AerospikeChatStorage, AerospikeConfig


async def test_factory_owns_reuses_and_idempotently_closes_client() -> None:
    session = object()
    client = Mock()
    client.connect = AsyncMock(return_value=client)
    client.create_session.return_value = session
    client.close = AsyncMock()
    factory = Mock(return_value=client)

    storage = await AerospikeChatStorage.connect(AerospikeConfig(), client_factory=factory)
    assert storage.session is session
    assert storage.session is session
    factory.assert_called_once()
    client.connect.assert_awaited_once()

    async with storage as entered:
        assert entered is storage
    await storage.close()
    client.close.assert_awaited_once()


async def test_borrowed_session_remains_open() -> None:
    session = Mock()
    session.close = AsyncMock()
    storage = AerospikeChatStorage(session)

    await storage.close()
    await storage.close()

    session.close.assert_not_awaited()


async def test_connect_configures_credentials_on_cluster_definition() -> None:
    session = object()
    client = Mock()
    client.create_session.return_value = session
    config = AerospikeConfig(
        username="user",
        password="pass",
    )
    with (
        patch("agent_squad_aerospike.storage.ClusterDefinition") as mock_cluster,
        patch("agent_squad_aerospike.storage.Behavior") as mock_behavior,
    ):
        builder = Mock()
        builder.with_native_credentials.return_value = builder
        builder.connect = AsyncMock(return_value=client)
        mock_cluster.return_value = builder
        mock_behavior.DEFAULT = Mock()
        mock_behavior.DEFAULT.derive_with_changes.return_value = "behavior"

        storage = await AerospikeChatStorage.connect(config)

    assert storage.session is session
    mock_cluster.assert_called_once()
    builder.with_native_credentials.assert_called_once_with("user", "pass")
    client.create_session.assert_called_once_with("behavior")
