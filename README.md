# Local Agent Radio

Local Agent Radio is an early prototype of a localhost-first message broker for people, LLM applications, and CLI agents. The planned service will provide durable, searchable private channels and a shared `public` channel through a CLI, HTTP/SSE, and MCP. Local critique is the default; optional remote review will receive only context a user explicitly selects.

## Current status

This repository contains the project plan, domain invariants, a transport-independent broker domain, and tests. The domain code covers identity and channel membership checks, sending and reading messages, cursor acknowledgement, and audit calls through interfaces. SQLite initializes the reserved `public` channel and registers an identity, its limited public membership, and a dedicated public credential in one transaction. An internal authenticator validates the token against its exact channel, expiry, and current identity and membership status. Tests use a real temporary SQLite file for registration and an in-memory fake for message behavior. Credential rotation and operator authorization, authentication and audit adapters, channel discovery, message storage, live following, a running daemon, CLI, HTTP/SSE, MCP, and critic integration are not implemented yet.

## Channel model

Private channels are invitation-only. The planned `public` channel is a shared local meeting place: registering an active agent or human grants a limited `public` membership automatically. A registered agent can post a request for help, and another agent can reply to that request. Each client chooses whether to follow `public` for live messages; membership alone does not start a stream, wake an agent, or advance its cursor. Messages stay in one durable log that members can read later. Authentication and membership are still required to read or post; `public` does not mean internet-facing or anonymous access. Public membership grants no access to private-channel messages or artifacts.

## How we are building it together

This is an interactive build. We work in small, reviewable steps rather than treating the [project plan](./PROJECT_PLAN.md) as a fixed specification:

1. **Choose a concrete behavior.** Describe what a person or agent needs to do, the privacy boundary, and what would demonstrate success.
2. **Record the decision.** Update the plan and, when it affects all interfaces, the [domain invariants](./docs/architecture/domain-invariants.md). Keep unresolved choices visible.
3. **Implement one slice.** Add the smallest useful domain, storage, or interface change, with tests for behavior and boundaries that matter.
4. **Run and review it.** Run the relevant tests, inspect the result, and use feedback to revise the next slice. As interfaces arrive, test a real exchange between independently launched clients.
5. **Keep the repository current.** Commit coherent increments and update this README when capabilities become usable, so the code, tests, and documentation describe the same state.

The first slices established the domain model, broker rules, automatic public-membership policy, durable registration, and a dedicated public credential. The next planned work is credential rotation and private-invitation rules. The [milestones](./PROJECT_PLAN.md#milestones) track the broader path to a usable local broker.

### Current pairing topic: identity, credentials, and SQLite transactions

An identity answers **who is acting**; a channel membership answers **which actions that identity may perform there**. Registering Agent A now follows this path:

1. [Open `RegistrationService.register()`](./src/local_agent_radio/domain/registration.py#L47). It creates an active identity and calls the public-membership policy. The policy grants an agent or human send, read, acknowledge, and search capabilities; a critic receives no automatic grant.
2. [Look at the credential issue function](./src/local_agent_radio/domain/credentials.py#L52). For a public member, it generates a random secret, stores only its SHA-256 digest in a credential record, scopes that record to the reserved `public` channel, and sets a 90-day expiry. The raw token is returned once after the transaction commits and is omitted from object representations.
3. [Look at `save_registration()`](./src/local_agent_radio/storage/registration.py#L150). SQLite inserts identity, membership, and credential inside one transaction. A failure at any insert rolls all three back. A version-one registration database upgrades to the credential schema without dropping existing identities or memberships. Existing version-one identities need a separate credential-issuance operation before they can authenticate; that operation is still planned.
4. [Look at `CredentialAuthenticator.authenticate()`](./src/local_agent_radio/domain/authentication.py#L32). It checks the secret, exact channel scope, expiry, active identity, and active membership. A public token is rejected for a private channel, even if that identity has been invited there. The broker still checks the capability required by the specific message operation.
5. Registration creates no follow connection or cursor movement. Following remains a separate client choice when that interface exists.

The [storage tests](./tests/test_registration_storage.py) reopen the database to prove persistence, inject failures at the membership and credential inserts to prove rollback, and verify that a public token cannot authenticate to a private channel. This registration path is trusted local provisioning code and is not exposed as an unauthenticated endpoint.

### Pair programming and discussing changes

We can work through a change together at any point, including before any code is written. Start with a behavior you want, a question about the design, or a file you want to understand. The assistant should explain the current behavior, propose a small next step, describe meaningful tradeoffs, and walk through the resulting code and tests in enough detail for you to challenge or redirect the work. You do not need to know the implementation details before starting the discussion.

For a change that affects channel access, privacy, data flow, or an external interface, we should discuss an example interaction and the boundary it crosses. Then we record the chosen rule in the plan or domain invariants, implement it in a reviewable slice, and check the behavior together. During a code walkthrough, the assistant should give clickable file-and-line links and short excerpts so you can follow along in the source pane without searching for symbol names. The assistant should suggest a pairing or design discussion when a choice has material consequences, while continuing work that is already clear and authorized.

Useful ways to start include:

- “Let's pair on how registering an agent grants access to `public`. Show me the flow before changing code.”
- “Walk through why following `public` stays optional even though membership is automatic.”
- “Walk me through this diff and the test that proves the behavior.”
- “What would change if a participant's access is revoked while it follows a channel?”

After a working session, the assistant should summarize what changed, why, what was tested, and what remains open. Your questions and corrections can change the plan; they are part of the build process.

## Run the current tests

Use Python 3.12 or newer from the repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

These tests run offline and do not require a model, API key, or server. The registration tests create a temporary SQLite database and remove it afterward.

## Repository

This project is intended for the public [`trent-alex/local-agent-radio`](https://github.com/trent-alex/local-agent-radio) repository. The project is still a prototype; the interfaces described in the plan are targets, not commands that work today.
