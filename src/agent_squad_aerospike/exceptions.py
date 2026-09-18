class AgentSquadAerospikeError(Exception):
    pass


class MessageTooLargeError(AgentSquadAerospikeError, ValueError):
    pass


class ConversationTooLargeError(AgentSquadAerospikeError):
    pass


class AmbiguousWriteError(AgentSquadAerospikeError):
    pass


class UnknownMessageSchemaError(AgentSquadAerospikeError, ValueError):
    pass


class DirectoryFullError(AgentSquadAerospikeError):
    pass
