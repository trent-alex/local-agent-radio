"""Ports the domain requires from persistence and auditing adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence
from uuid import UUID

from .models import Cursor, Membership, Message, MessageKind


@dataclass(frozen=True, slots=True)
class AppendMessage:
    channel_id: UUID
    sender_id: UUID
    kind: MessageKind
    body: str
    parent_id: UUID | None
    idempotency_key: str | None


@dataclass(frozen=True, slots=True)
class AppendResult:
    message: Message
    created: bool


class BrokerRepository(Protocol):
    """Atomic persistence operations needed by the broker domain service."""

    def get_membership(self, channel_id: UUID, identity_id: UUID) -> Membership | None: ...

    def append_message(self, command: AppendMessage) -> AppendResult:
        """Atomically enforce idempotency, allocate sequence, and store a message."""
        ...

    def read_messages(
        self, channel_id: UUID, *, after_sequence: int, limit: int
    ) -> Sequence[Message]: ...

    def record_delivery(
        self, channel_id: UUID, identity_id: UUID, sequence: int
    ) -> Cursor:
        """Atomically advance, but never reduce, the delivered cursor."""
        ...

    def acknowledge(
        self, channel_id: UUID, identity_id: UUID, sequence: int
    ) -> Cursor:
        """Atomically advance acknowledgement if sequence has been delivered."""
        ...


class AuditSink(Protocol):
    def record(
        self,
        *,
        actor_id: UUID,
        action: str,
        target_id: UUID,
        outcome: str,
        correlation_id: UUID,
    ) -> None: ...
