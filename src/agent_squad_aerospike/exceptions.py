class AgentSquadAerospikeError(Exception):
    pass


class ConversationTooLargeError(AgentSquadAerospikeError):
    pass


class AmbiguousWriteError(AgentSquadAerospikeError):
    pass


class UnknownMessageSchemaError(AgentSquadAerospikeError, ValueError):
    pass


class DirectoryFullError(AgentSquadAerospikeError):
    pass
