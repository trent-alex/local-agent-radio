# Domain invariants

These rules define the transport-independent behavior of Local Agent Radio. HTTP,
SSE, MCP, the CLI, and storage adapters must preserve them rather than implement
different versions of them.

## Identity and authorization

1. Every operation has one authenticated actor identity. Display names are never
   used for authorization.
2. Access is denied unless the actor identity is active and an active channel
   membership explicitly grants the required capability.
3. Private channels require an invitation or administrative grant. Registration
   of an active human or agent identity also creates a limited membership in the
   reserved `public` channel in the same transaction. Critic identities receive
   no automatic public membership. Automatic provisioning never overwrites a
   revoked public membership.
4. Revocation takes effect before the next operation. An existing connection or
   previously issued credential does not preserve revoked authority.
5. Administrative authority is separate from ordinary send, read, acknowledge,
   artifact, and review capabilities.

## Channels and messages

1. Channel and identity IDs are opaque UUIDs. Channel names are unique labels,
   not security boundaries.
2. `public` means shared within one local broker, not anonymous or internet
   access. Discovery reveals no private channel names or content. A public
   channel cannot be used to read another channel's messages or artifacts.
3. A committed message is immutable. Corrections and deletions are represented by
   later records rather than silent mutation of history.
4. Each committed message has a positive sequence number that is unique within
   its channel. Committed sequence numbers increase in publication order.
5. Assigning the sequence number and committing the message is one atomic storage
   operation. A failed transaction cannot publish a sequence number.
6. An agent may post a `request` message in `public` to solicit help. Replies
   link to the request through `parent_id`; parent message IDs must refer to a
   message in the same channel. Delivery remains a shared channel log, not a
   separate copy or guaranteed assignment to every agent.
7. An idempotency key is scoped to the actor, channel, and operation. Repeating a
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
7. Membership does not start a live stream, wake a client, or advance its cursor.
   Each client opts in to following `public` by opening a follow or bounded wait
   operation; it may read retained history later without having followed live.

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
