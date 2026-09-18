# Implementation notes

## Aerospike Developer SDK 0.9.0a5

The Community Edition spike confirms that one `session.upsert(key)` write segment can combine an AEL filter, `list_append_items`, `list_trim`, scalar metadata writes, and record expiration. The filter `not($.msgs.exists()) or $.msgs.count() == 0 or $.msgs.[-1].role != <role>` works for missing records and existing list bins. `list_trim(-limit, limit)` retains whole newest entries after the append.

Single-key failures raise `AerospikeError`; batch failures are carried by each `RecordResult`. Result codes are values from the SDK's public `aerospike_async.ResultCode` dependency rather than Python enums with a `name` attribute. `RecordResult.in_doubt` must be checked before result-code translation. `FILTERED_OUT` represents intentional role suppression, `KEY_NOT_FOUND_ERROR` is tolerated only where absence is valid, and `RECORD_TOO_BIG` maps to the package conversation-size exception.

The SDK's default behavior retries writes. Non-idempotent conversation appends must therefore use a derived behavior with zero write retries before release; directory map upserts may use independent retry behavior because they are idempotent.
