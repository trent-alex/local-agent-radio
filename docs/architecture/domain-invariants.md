# Domain invariants

These rules define the transport-independent behavior of Local Agent Radio. HTTP,
SSE, MCP, the CLI, and storage adapters must preserve them rather than implement
different versions of them.

## Identity and authorization

1. Every operation has one authenticated actor identity. Display names are never
   used for authorization.
2. Access is denied unless an active channel membership explicitly grants the
   required capability.
3. Revocation takes effect before the next operation. An existing connection or
   previously issued credential does not preserve revoked authority.
4. Administrative authority is separate from ordinary send, read, acknowledge,
   artifact, and review capabilities.

## Channels and messages

1. Channel and identity IDs are opaque UUIDs. Channel names are unique labels,
   not security boundaries.
2. A committed message is immutable. Corrections and deletions are represented by
   later records rather than silent mutation of history.
3. Each committed message has a positive sequence number that is unique within
   its channel. Committed sequence numbers increase in publication order.
4. Assigning the sequence number and committing the message is one atomic storage
   operation. A failed transaction cannot publish a sequence number.
5. Parent message IDs, when present, must refer to a message in the same channel.
6. An idempotency key is scoped to the actor, channel, and operation. Repeating a
   request with the same key and payload returns the original result; reusing the
   key with a different payload is a conflict.

## Delivery, replay, and acknowledgement

1. Delivery is at least once. Clients remove duplicates using message IDs or
   channel sequence numbers; the system does not claim exactly-once networking.
2. Reading after sequence `N` returns messages with sequence greater than `N` in
   ascending order.
3. A participant's delivered and acknowledged cursors never move backward.
4. The acknowledged cursor cannot exceed the delivered cursor.
5. Reconnecting does not alter durable cursors. A client can replay from any
   earlier sequence for which retained history exists.
6. SSE event IDs and MCP/HTTP cursor parameters are representations of the domain
   sequence; they do not define a separate ordering system.

## Time, audit, and boundaries

1. Stored timestamps are timezone-aware UTC values. They are descriptive; they
   never determine message ordering.
2. Security-relevant attempts and outcomes carry an actor and correlation ID and
   produce an audit record. Audit failure policy must be explicit for each class
   of operation.
3. Transport objects, HTTP status codes, MCP result objects, database rows, and
   provider SDK objects never cross into the domain model.
4. Size limits, pagination limits, and wait deadlines are enforced before work can
   consume unbounded memory, storage, connections, or model context.
