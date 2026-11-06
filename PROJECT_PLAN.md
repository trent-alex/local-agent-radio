# Local Agent Radio — Project Plan

## Objective

Build a small, private coordination service that lets local LLM applications, CLI agents, and people exchange messages through shared channels. The service runs on one machine, binds to `127.0.0.1` by default, keeps durable and searchable history locally, and exposes the same core capabilities through a CLI, HTTP API, live event stream, and MCP tools.

Local critique is the default. A remote critic is an explicit, mediated option: it receives only user-selected messages, summaries, diffs, or artifact chunks. The complete transcript and artifacts never leave the machine unless included in an auditable export manifest.

## MVP success criteria

- Two independently launched agents can authenticate, join a channel, exchange messages, wait for new work, and resume from a durable cursor after restart.
- A person can send, read, follow, and search channel history from a human-friendly CLI.
- Clients can use HTTP plus Server-Sent Events (SSE), or the equivalent MCP tools, without sharing implementation details.
- SQLite remains the source of truth and supports full-text message search.
- A local OpenAI-compatible endpoint (including Ollama's compatible API) can critique selected context.
- A disabled-by-default remote critic can review an explicit context bundle without direct access to the broker, localhost, or arbitrary local files.
- Every authentication, context-export, critic, and tool-call event needed for an audit is recorded locally.
- The project can live in the public `trent-alex/local-agent-radio` GitHub repository without machine-specific paths or embedded secrets.

## User stories

- As a CLI agent, I can post a result and block for a reply without polling aggressively.
- As an agent that restarts, I can continue from my last acknowledged message.
- As a person, I can inspect live traffic and search prior decisions across a channel.
- As a local critic, I can review a bounded set of messages and artifact chunks without receiving the entire transcript.
- As a user invoking a remote critic, I can preview or inspect exactly what will be sent and see what was sent afterward.
- As an operator, I can create identities, scope or rotate channel credentials, and trace who performed each action.
- As a containerized client, I can reach the host service through an explicitly configured route without weakening the default host-only posture.

## Non-goals

- Reimplementing Plasma Radio or maintaining compatibility with it.
- A hosted service, multi-machine federation, internet-facing deployment, or mobile UI.
- A general job scheduler, autonomous agent framework, or model-training system.
- End-to-end encryption between mutually distrustful local participants in the MVP.
- Storing arbitrary binary data inside SQLite, semantic/vector search, or long-term archival policy automation.
- Giving remote models direct network, filesystem, shell, MCP, or localhost access.
- Perfect isolation from other processes running as the same operating-system user; the threat model focuses on explicit credentials, least privilege, and auditable mediation.

## Proposed architecture

Use one deployable daemon with internal modules rather than microservices. A practical starting stack is Python 3.12, FastAPI/Starlette, the official MCP Python SDK, Typer, and SQLite with WAL and FTS5. Keep domain logic independent of those adapters so the runtime can be changed later.

```text
CLI clients ─────── HTTP/SSE ─┐
LLM applications ─ HTTP/SSE ─┼─> Local Agent Radio daemon
Agent clients ─────── MCP ────┘       │
                                       ├─ broker + identity/policy service
                                       ├─ SQLite + FTS5
                                       ├─ managed artifact directory
                                       └─ critic coordinator
                                            ├─ local OpenAI-compatible endpoint
                                            └─ optional remote API
```

SSE is the MVP live-delivery transport: clients post commands over HTTP and receive ordered channel events through one reconnectable stream. It is simpler to operate and audit than a bidirectional WebSocket. A WebSocket adapter can be added later if a client demonstrates a real need.

### Component boundaries

1. **Broker/domain layer** — validates identities and channel membership; assigns monotonically increasing per-channel sequence numbers; persists messages transactionally; manages acknowledgements and bounded waits.
2. **Storage layer** — owns migrations, SQLite WAL transactions, FTS5 indexing, cursor recovery, retention hooks, and artifact metadata. No transport-specific objects cross this boundary.
3. **HTTP/SSE adapter** — provides versioned JSON endpoints, bearer-token authentication, pagination, resumable SSE using the last sequence, request limits, and health/readiness endpoints.
4. **MCP adapter** — maps a deliberately small tool set onto the same domain operations. It adds no privileged back door; the MCP session acts as a registered participant.
5. **CLI** — a thin API client for people and shell scripts. It stores endpoint and token references in a user-only config file and supports JSON output for automation.
6. **Artifact store** — copies explicitly imported files into a managed data directory, records content hashes and metadata, and returns bounded text/binary chunks. It never accepts arbitrary read paths from an agent tool call.
7. **Critic coordinator** — builds a context bundle, enforces route-specific budgets and policy, calls a local or remote OpenAI-compatible API, mediates any follow-up context requests, and posts the final review back to the channel.

## Data model

All identifiers are opaque UUIDs. Messages also receive a channel-local integer `sequence` for ordering and resume behavior.

| Entity | Essential fields and purpose |
| --- | --- |
| `channels` | `id`, unique `name`, timestamps, policy/settings JSON |
| `identities` | `id`, display name, kind (`human`, `agent`, `critic`), status, timestamps; one stable identity may join several channels |
| `channel_memberships` | channel/identity pair, role, capabilities, join/revoke timestamps |
| `credentials` | identity and optional channel scope, token hash, capabilities, expiry, rotation/revocation timestamps; plaintext secrets are never stored |
| `messages` | `id`, `channel_id`, `sequence`, `sender_id`, optional parent/thread ID, kind, body, metadata JSON, timestamp |
| `message_fts` | FTS5 projection of searchable message text and selected metadata |
| `cursors` | participant/channel, last delivered sequence, last acknowledged sequence, updated timestamp |
| `artifacts` | `id`, channel/owner, managed relative path, original name, media type, byte size, digest, metadata, timestamp |
| `summaries` | channel, source sequence range, model/route, text, token estimate, provenance, timestamp |
| `reviews` | requester, critic route/model, status, input-manifest ID, budgets, result message ID, usage/error data |
| `context_exports` | immutable manifest of selected message, summary, diff, and artifact-chunk references plus hashes and destination |
| `tool_calls` | review/session, tool name, bounded arguments/result metadata, status, timestamps |
| `audit_events` | actor, action, target, outcome, request correlation ID, safe metadata, timestamp |

Large artifact bytes live in the managed artifact directory, not SQLite. An artifact chunk is addressed by artifact ID plus offset/range; reads are capped and audited. Database migrations are forward-only and backed up before destructive changes.

## Interfaces

### CLI

The command name is tentatively `radio`.

```text
radio init
radio serve [--host 127.0.0.1] [--port 7337]
radio status
radio channel create|list|show
radio identity create|list|revoke
radio token issue|rotate|revoke
radio send CHANNEL MESSAGE [--file PATH]
radio read CHANNEL [--after SEQ] [--limit N] [--json]
radio follow CHANNEL [--after SEQ]
radio search QUERY [--channel CHANNEL] [--json]
radio artifact add|show|chunk
radio review CHANNEL --critic local|remote --messages RANGE [--artifact ID:RANGE] [--dry-run]
radio audit [--channel CHANNEL] [--since TIME]
```

`review --dry-run` emits the context-export manifest and estimated size without calling a model. Secrets should be accepted through protected files, environment variables, or stdin, never command-line flags that leak through process listings.

### HTTP API

Use `/v1` and JSON throughout. The smallest useful surface is:

- `POST /v1/channels`, `GET /v1/channels`
- `POST /v1/channels/{id}/participants` and credential rotate/revoke endpoints
- `POST /v1/channels/{id}/messages`
- `GET /v1/channels/{id}/messages?after=&limit=`
- `GET /v1/channels/{id}/events?after=` (SSE with heartbeat and resumable sequence IDs)
- `GET /v1/search?q=&channel_id=&before=&after=`
- `POST /v1/channels/{id}/artifacts`, `GET /v1/artifacts/{id}`, `GET /v1/artifacts/{id}/chunks?offset=&length=`
- `POST /v1/channels/{id}/reviews`, `GET /v1/reviews/{id}`
- `GET /v1/context-exports/{id}` and `GET /v1/audit-events`
- `GET /healthz`, `GET /readyz`

Mutation requests accept an idempotency key. List endpoints use stable sequence/cursor pagination. Error bodies use one documented shape and never echo credentials or unredacted provider responses.

### MCP tools

- `send_message(channel, body, kind?, parent_id?, idempotency_key?)`
- `read_messages(channel, after?, before?, limit?)`
- `wait_for_message(channel, after?, timeout_seconds?)`
- `search_messages(query, channel?, before?, after?, limit?)`
- `get_artifact_chunk(artifact_id, offset?, length?)`
- `post_review(channel, review, subject_message_ids?, metadata?)`
- `request_more_context(review_id, reason, message_ids?, artifact_chunks?)`

`wait_for_message` is a bounded server-side wait, not an infinite MCP call. `request_more_context` creates a local request for policy evaluation; it does not let a remote model fetch content directly. Administrative identity, token, and channel operations remain CLI/API-only in the MVP.

## Critic routing and context budgeting

The coordinator uses the same review pipeline for both routes:

1. Resolve the user's explicit selection into message IDs, summary ranges, diffs, and artifact chunk ranges.
2. Canonicalize and hash an immutable context-export manifest.
3. Apply per-review limits for input tokens/bytes, artifact bytes, output tokens, follow-up rounds, latency, and estimated remote cost.
4. For `local`, send the bundle to a configured OpenAI-compatible base URL, defaulting to a loopback Ollama-compatible endpoint. No internet access is required.
5. For `remote`, require that the route is enabled and the selection is explicit; show the manifest in dry-run/approval flows; send only the selected bundle through the coordinator.
6. If the critic asks for more context, translate the request into `request_more_context`, re-run local policy/user approval as configured, and append only the approved chunks. Cap the number of rounds.
7. Store provider, model, hashes, usage, budgets, tool-call metadata, and the resulting review locally. Do not store API secrets or hidden reasoning.

Summaries are derived context, not replacements for source messages. They record their source sequence range and model. Remote tokens still incur provider processing and cost; selection and summarization reduce transferred context but do not make it free.

Remote critic configuration is off by default. The MVP supports a generic OpenAI-compatible remote provider rather than provider-specific agent hosting. The remote model receives no callable network or filesystem tools; all apparent tools terminate at the local coordinator and are checked against the review manifest and budget.

## Privacy, security, and threat model

### Protected assets

Channel messages, artifacts, credentials, identity mappings, context exports, reviews, provider secrets, and audit history.

### Material threats

- An unrelated local process connects to the loopback port or steals a bearer token.
- An authorized but compromised agent reads another channel, impersonates a participant, floods storage, or submits malicious content.
- Prompt injection in a message or artifact persuades a critic to request or reveal unrelated local context.
- Path traversal, symlink tricks, oversized ranges, or malformed content escape the artifact store.
- A remote route accidentally exports more context than selected, or logs credentials/sensitive provider payloads.
- Container networking encourages an operator to bind the service broadly and expose it to the LAN.

### MVP controls

- Treat loopback binding as exposure reduction, not authentication. Require random per-identity bearer tokens scoped to one channel (or narrowly defined administration), store only hashes, support expiry/revocation/rotation, and compare secrets safely.
- Authorize every domain operation, including SSE resume, search, artifact reads, and critic follow-up requests. Record actor and correlation IDs.
- Copy imports into a private managed directory with canonical generated names; reject special files, traversal, symlinks, and over-limit content. Verify digest and size before serving bounded chunks.
- Apply request/body limits, pagination caps, SSE connection limits, review concurrency limits, timeouts, and configurable disk quotas. Use SQLite busy timeouts and WAL checkpoints.
- Mark messages and artifacts as untrusted critic input. Tool-like text inside them has no authority. Only structured coordinator requests can select additional context.
- Keep remote routing disabled until configured. Build outbound payloads exclusively from the immutable export manifest, allowlist destination base URLs, redact secrets, and provide dry-run inspection. Audit each outbound attempt and its content hashes.
- Keep full transcripts, artifact bytes, indexes, summaries, and audits local. Never add telemetry or crash-report uploads without a separate opt-in.
- Store database, artifacts, config, and secret files with user-only permissions. Recommend OS disk encryption; document that same-user processes and machine administrators remain outside strong isolation.

### Docker-host connectivity

The daemon still binds to `127.0.0.1` by default. A client container cannot normally reach that socket directly. Prefer one of these explicit configurations:

1. Run the MCP adapter or client on the host.
2. On Docker Desktop, target `host.docker.internal` and make the daemon listen on a host interface reachable by Docker, protected by scoped tokens and the host firewall.
3. On Linux, add `host.docker.internal:host-gateway` and use an explicitly chosen Docker bridge/gateway bind address.
4. Later, offer a Unix-domain socket mounted read/write into trusted containers; this is safer than a broad TCP bind but need not block the MVP.

Never recommend `0.0.0.0` as a convenience default. The CLI should warn when the configured bind address is non-loopback and require an explicit acknowledgement.

## Repository integration plan

The selected destination is the public `trent-alex/local-agent-radio` GitHub repository. Local Agent Radio is the primary application at the repository root. Keep the source portable and verify the repository contents before each push.

### Self-contained package boundary

Keep application code under `src/local_agent_radio/`, with public entry points for the CLI, HTTP application factory, and MCP adapter. Domain, storage, transport, artifact, critic, identity/policy, and configuration modules remain internal to that package. Keep database migrations inside the package, tests under `tests/`, runnable clients under `examples/`, and architecture, operations, decisions, and learning notes under `docs/`.

The package must not import unpublished code from a parent repository. Configuration is supplied through command-line options, environment variables, or a platform-appropriate user config directory. Repository files may use repository-relative paths, while runtime database, artifact, credential, and log locations resolve from configuration or user data directories. Source, tests, documentation, and examples must contain no absolute paths from this planning machine.

### Repository layout

Put `pyproject.toml`, `src/local_agent_radio/`, `tests/`, `docs/`, `examples/`, and project-level contribution and security files at the repository root as they become relevant. The root README is the product overview, current status, and record of the interactive build process.

### Repository hygiene

- Provide one documented contributor path: supported Python version, virtual-environment creation, editable installation with development dependencies, and commands for formatting, linting, type checking, tests, and running the daemon.
- Add a minimal CI workflow for pull requests and the default branch. It should install the declared development dependencies and run formatting checks, linting, type checking, and the offline test suite on Linux with the supported Python version. It must not require provider secrets, Ollama, Docker, or paid APIs.
- Keep examples secret-free. Use placeholder values in an optional `.env.example`, keep remote critics disabled, and ensure fake providers cover all default tests. Never commit local tokens, databases, artifacts, logs, model payloads, or user-specific configuration.
- Inspect the destination repository's license before import. Reuse it only when it is compatible with intended distribution and all direct dependencies; otherwise resolve licensing explicitly before source code is added. Record dependency licenses and attribution requirements.
- Follow existing destination conventions for issue templates, contribution files, changelog/release notes, formatting, branch protection, and CI rather than introducing competing mechanisms.

### Migration/import checklist

1. Create or inspect `trent-alex/local-agent-radio`, confirm its default branch, maintainers, and repository license.
2. Compare its contribution, dependency, CI, formatting, naming, and documentation conventions before adding new repository-wide files.
3. Copy the planning files and eventual self-contained package into that path without carrying runtime data, ignored files, local credentials, caches, or machine-specific settings.
4. Search for absolute paths, secrets, private endpoints, personal identifiers, generated databases/artifacts, and references that only work in this workspace; replace them with portable configuration or fixtures.
5. Merge dependency metadata, ignore rules, documentation navigation, and CI invocation with the destination repository instead of overwriting existing files.
6. Run formatting, linting, type checking, unit/integration tests, packaging checks, and secret scanning from both the destination repository root and the package's supported working directory.
7. Verify clean-clone contributor setup, local-only default behavior, migration discovery, example commands, and artifact/database placement on macOS and Linux.
8. Review the import as a normal change set. Push to the selected public repository after checking the staged files and commit metadata.

## Testing approach

- **Unit tests:** authorization matrix, sequence allocation, cursors, search query handling, manifest construction, budgets, redaction, path/range validation, and provider response normalization.
- **Storage tests:** migrations, FTS consistency, WAL concurrency, crash/restart recovery, idempotent sends, backup/restore, and quota behavior against real temporary SQLite databases.
- **Contract tests:** CLI, HTTP error schema, SSE reconnect/ordering, and all MCP tools share fixtures and assert identical domain outcomes.
- **Critic tests:** fake local and remote OpenAI-compatible servers verify exact outbound payloads, token/byte caps, follow-up mediation, failures, retries, cancellation, and usage recording. A no-egress test proves remote-disabled operation makes no network call.
- **Security tests:** cross-channel access denial, revoked/expired tokens, token leakage checks, malicious search input, traversal/symlink/special-file cases, oversized payloads, prompt-injected tool requests, and non-loopback bind warnings.
- **End-to-end tests:** two agents plus a human CLI exchange messages, restart the daemon, resume cursors, attach an artifact, run a local review, and inspect the audit trail.
- **Compatibility tests:** macOS/Linux and host-to-container connectivity. Keep Windows as best-effort until a maintainer commits to it.

Tests must not require a real model or paid API. Optional smoke tests may target a locally running Ollama instance and an explicitly supplied remote test key.

## Milestones

### M0 — Decisions and executable specification

- Confirm the remaining open decisions below.
- Write API/MCP schemas, authorization matrix, database migration 001, and end-to-end acceptance fixtures.
- Establish the portable package boundary, contributor setup, destination-aware import checklist, and secret-free CI contract.

### M1 — Durable local broker

- Implement daemon configuration, SQLite/FTS5 storage, channels, identities, credentials, messages, cursors, search, audit events, and core CLI commands.
- Demonstrate restart-safe exchange between two CLI participants.

### M2 — Live and agent interfaces

- Add resumable SSE, the MCP adapter and seven MCP tools, artifact import/chunking, limits, and contract tests.
- Demonstrate two heterogeneous clients communicating through one channel.

### M3 — Critic coordinator

- Add immutable context manifests, budgets, local OpenAI-compatible critique, optional remote routing, follow-up mediation, dry-run inspection, and review/audit records.
- Demonstrate that a remote test server sees only selected content.

### M4 — Hardening and packaging

- Complete security abuse tests, backup/restore documentation, non-loopback warnings, Docker-host recipes, graceful shutdown, and installation packaging.
- Cut an MVP release only after the success criteria pass on macOS and Linux.

## Decisions requiring user input

These are intentionally limited; recommended defaults let implementation begin immediately after confirmation.

1. **Runtime:** approve Python 3.12 + FastAPI + MCP Python SDK + Typer, or require another stack? Recommended: approve it for speed and local-model ecosystem support.
2. **Artifact import:** copy selected files into the managed store, or retain references to original paths? Recommended: copy, which gives stable hashes and avoids later arbitrary-path access.
3. **Remote review consent:** require approval for every remote export, or allow saved per-channel policies after the first approval? Recommended: per-export approval for the MVP, with `--dry-run` available everywhere.
4. **Initial distribution:** prioritize `pipx`/virtualenv installation or a packaged container? Recommended: `pipx` first because the broker is host-local; provide a client-container recipe in M4.

## Deferred after MVP

WebSockets, Unix-domain-socket transport, vector/semantic search, encrypted channel payloads, retention automation, remote federation, a web UI, provider-specific adapters, richer roles, distributed workers, and multi-host synchronization should wait for demonstrated demand.
