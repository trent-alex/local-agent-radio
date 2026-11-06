"""Application-facing operations that enforce domain policy."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from .errors import AuthorizationDenied
from .models import Capability, Cursor, Message, MessageKind
from .ports import AppendMessage, AuditSink, BrokerRepository


class BrokerService:
    """Transport-independent message broker use cases."""

    MAX_READ_LIMIT = 100

    def __init__(self, repository: BrokerRepository, audit: AuditSink) -> None:
        self._repository = repository
        self._audit = audit

    def send_message(
        self,
        *,
        actor_id: UUID,
        channel_id: UUID,
        body: str,
        correlation_id: UUID,
        kind: MessageKind = MessageKind.TEXT,
        parent_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> Message:
        self._require_capability(
            actor_id,
            channel_id,
            Capability.SEND_MESSAGES,
            action="message.send",
            correlation_id=correlation_id,
        )
        result = self._repository.append_message(
            AppendMessage(
                channel_id=channel_id,
                sender_id=actor_id,
                kind=kind,
                body=body,
                parent_id=parent_id,
                idempotency_key=idempotency_key,
            )
        )
        self._audit.record(
            actor_id=actor_id,
            action="message.send",
            target_id=result.message.id,
            outcome="created" if result.created else "replayed",
            correlation_id=correlation_id,
        )
        return result.message

    def read_messages(
        self,
        *,
        actor_id: UUID,
        channel_id: UUID,
        after_sequence: int,
        limit: int,
        correlation_id: UUID,
    ) -> Sequence[Message]:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        if not 1 <= limit <= self.MAX_READ_LIMIT:
            raise ValueError(f"limit must be between 1 and {self.MAX_READ_LIMIT}")
        self._require_capability(
            actor_id,
            channel_id,
            Capability.READ_MESSAGES,
            action="message.read",
            correlation_id=correlation_id,
        )
        messages = tuple(
            self._repository.read_messages(
                channel_id, after_sequence=after_sequence, limit=limit
            )
        )
        if messages:
            self._repository.record_delivery(
                channel_id,
                actor_id,
                messages[-1].sequence,
            )
        self._audit.record(
            actor_id=actor_id,
            action="message.read",
            target_id=channel_id,
            outcome="succeeded",
            correlation_id=correlation_id,
        )
        return messages

    def acknowledge(
        self,
        *,
        actor_id: UUID,
        channel_id: UUID,
        acknowledged_sequence: int,
        correlation_id: UUID,
    ) -> Cursor:
        if acknowledged_sequence < 0:
            raise ValueError("acknowledged_sequence cannot be negative")
        self._require_capability(
            actor_id,
            channel_id,
            Capability.ACKNOWLEDGE_MESSAGES,
            action="message.acknowledge",
            correlation_id=correlation_id,
        )
        saved = self._repository.acknowledge(
            channel_id,
            actor_id,
            acknowledged_sequence,
        )
        self._audit.record(
            actor_id=actor_id,
            action="message.acknowledge",
            target_id=channel_id,
            outcome="succeeded",
            correlation_id=correlation_id,
        )
        return saved

    def _require_capability(
        self,
        actor_id: UUID,
        channel_id: UUID,
        capability: Capability,
        *,
        action: str,
        correlation_id: UUID,
    ) -> None:
        membership = self._repository.get_membership(channel_id, actor_id)
        if membership is None or not membership.permits(capability):
            self._audit.record(
                actor_id=actor_id,
                action=action,
                target_id=channel_id,
                outcome="denied",
                correlation_id=correlation_id,
            )
            raise AuthorizationDenied(
                f"identity {actor_id} lacks {capability.value} in channel {channel_id}"
            )
