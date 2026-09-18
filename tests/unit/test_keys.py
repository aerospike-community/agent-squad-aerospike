from __future__ import annotations

from agent_squad_aerospike._keys import conversation_key, directory_key


def test_conversation_key_matches_independent_unicode_vector() -> None:
    assert conversation_key("a", "bc", "é") == (
        "900512015a577db31e9c2239a7afadda04208b459b98c8d5750d016dfceff819"
    )


def test_length_prefixing_prevents_delimiter_collisions() -> None:
    assert conversation_key("a:b", "c", "d") == (
        "cd5b8c5195813fe53c009250818f50a513b7c6c1db590e3e0008440f8b0d44ee"
    )
    assert conversation_key("a", "b:c", "d") == (
        "588cde4df4839b8b2fa53c125f989287d77f6001f4786978944b552a19357bfd"
    )


def test_key_domains_are_separate() -> None:
    assert directory_key("a", "bc") == (
        "de9d715a21f95a9f7ec056eb36d2f2bd6c6eaba47f0a569fc692e6a9a67f7ab2"
    )
    assert directory_key("a", "bc") != conversation_key("a", "bc", "")
