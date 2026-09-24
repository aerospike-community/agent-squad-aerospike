# Compatibility

The initial release supports `agent-squad>=1.1.3,<1.2` on Python 3.11 through 3.14 and targets the pre-release Aerospike Developer SDK range `aerospike-sdk>=0.9.0a5,<0.10`.

Agent Squad 1.1.3 defines an asynchronous `ChatStorage` interface with boolean `save_chat_message` and `save_chat_messages` results. Save inputs accept `ConversationMessage` or `TimestampedMessage`. Fetches return `ConversationMessage` values. A `ConversationMessage` carries a participant role, complete optional list-valued content, and optional citations. `TimestampedMessage` adds an epoch-millisecond timestamp.

The public test seam consists of `AerospikeChatStorage`, immutable public configuration, lifecycle methods, and package exceptions. Distribution smoke tests exercise both wheel and sdist. Deterministic key and message codecs remain private but receive focused direct tests.
