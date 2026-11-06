"""Pure domain values for Local Agent Radio."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _require_text(value: str, field_name: str, *, maximum: int) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")


class IdentityKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    CRITIC = "critic"


class IdentityStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class MembershipRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"
    CRITIC = "critic"


class Capability(StrEnum):
    SEND_MESSAGES = "send_messages"
    READ_MESSAGES = "read_messages"
    ACKNOWLEDGE_MESSAGES = "acknowledge_messages"
    SEARCH_MESSAGES = "search_messages"
    READ_ARTIFACTS = "read_artifacts"
    REQUEST_REVIEWS = "request_reviews"
    ADMINISTER_CHANNEL = "administer_channel"


class MessageKind(StrEnum):
    TEXT = "text"
    REVIEW = "review"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Identity:
    id: UUID
    display_name: str
    kind: IdentityKind
    status: IdentityStatus
    created_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.display_name, "display_name", maximum=100)
        _require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class Channel:
    id: UUID
    name: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.name, "name", maximum=128)
        _require_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class Membership:
    channel_id: UUID
    identity_id: UUID
    role: MembershipRole
    capabilities: frozenset[Capability]
    joined_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_utc(self.joined_at, "joined_at")
        if self.revoked_at is not None:
            _require_utc(self.revoked_at, "revoked_at")
            if self.revoked_at < self.joined_at:
                raise ValueError("revoked_at cannot precede joined_at")

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def permits(self, capability: Capability) -> bool:
        return self.active and capability in self.capabilities


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    channel_id: UUID
    sequence: int
    sender_id: UUID
    kind: MessageKind
    body: str
    created_at: datetime
    parent_id: UUID | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must be positive")
        _require_text(self.body, "body", maximum=1_000_000)
        _require_utc(self.created_at, "created_at")
        if self.idempotency_key is not None:
            _require_text(self.idempotency_key, "idempotency_key", maximum=128)


@dataclass(frozen=True, slots=True)
class Cursor:
    channel_id: UUID
    identity_id: UUID
    last_delivered_sequence: int = 0
    last_acknowledged_sequence: int = 0

    def __post_init__(self) -> None:
        if self.last_delivered_sequence < 0:
            raise ValueError("last_delivered_sequence cannot be negative")
        if self.last_acknowledged_sequence < 0:
            raise ValueError("last_acknowledged_sequence cannot be negative")
        if self.last_acknowledged_sequence > self.last_delivered_sequence:
            raise ValueError("acknowledged sequence cannot exceed delivered sequence")

    def record_delivery(self, sequence: int) -> Cursor:
        if sequence < self.last_delivered_sequence:
            raise ValueError("delivered cursor cannot move backward")
        return replace(self, last_delivered_sequence=sequence)

    def acknowledge(self, sequence: int) -> Cursor:
        if sequence < self.last_acknowledged_sequence:
            raise ValueError("acknowledged cursor cannot move backward")
        if sequence > self.last_delivered_sequence:
            raise ValueError("cannot acknowledge an undelivered sequence")
        return replace(self, last_acknowledged_sequence=sequence)
