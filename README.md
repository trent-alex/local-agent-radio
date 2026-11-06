# Local Agent Radio

Local Agent Radio is an early prototype of a private, localhost-first message broker for people, LLM applications, and CLI agents. The planned service will provide durable, searchable channels through a CLI, HTTP/SSE, and MCP. Local critique is the default; optional remote review will receive only context a user explicitly selects.

## Current status

This repository contains the project plan, domain invariants, a transport-independent broker domain, and unit tests. The domain code currently covers channel membership checks, sending and reading messages, cursor acknowledgement, and audit calls through interfaces. The tests use an in-memory fake repository. There is no running daemon, SQLite store, CLI, HTTP/SSE or MCP adapter, or critic integration yet.

## How we are building it together

This is an interactive build. We work in small, reviewable steps rather than treating the [project plan](./PROJECT_PLAN.md) as a fixed specification:

1. **Choose a concrete behavior.** Describe what a person or agent needs to do, the privacy boundary, and what would demonstrate success.
2. **Record the decision.** Update the plan and, when it affects all interfaces, the [domain invariants](./docs/architecture/domain-invariants.md). Keep unresolved choices visible.
3. **Implement one slice.** Add the smallest useful domain, storage, or interface change, with tests for behavior and boundaries that matter.
4. **Run and review it.** Run the relevant tests, inspect the result, and use feedback to revise the next slice. As interfaces arrive, test a real exchange between independently launched clients.
5. **Keep the repository current.** Commit coherent increments and update this README when capabilities become usable, so the code, tests, and documentation describe the same state.

The first slice established the domain model and broker rules. The next planned work is to finish the executable specification and add durable SQLite storage for messages and cursors. The [milestones](./PROJECT_PLAN.md#milestones) track the broader path to a usable local broker.

## Run the current tests

Use Python 3.12 or newer from the repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

These tests run offline and do not require a model, API key, or server.

## Repository

This project is intended for the public [`trent-alex/local-agent-radio`](https://github.com/trent-alex/local-agent-radio) repository. The project is still a prototype; the interfaces described in the plan are targets, not commands that work today.
