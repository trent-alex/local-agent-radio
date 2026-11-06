from datetime import UTC, datetime
from unittest import TestCase
from uuid import UUID, uuid4

from local_agent_radio.domain import (
    AuthorizationDenied,
    BrokerService,
    Capability,
    Cursor,
    Identity,
    IdentityKind,
    IdentityStatus,
    Membership,
    MembershipRole,
    Message,
    MessageKind,
)
from local_agent_radio.domain.ports import AppendResult


NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(
        self, membership: Membership | None, actor: Identity | None = None
    ) -> None:
        self.membership = membership
        self.actor = actor
        if self.actor is None and membership is not None:
            self.actor = Identity(
                id=membership.identity_id,
                display_name="Test actor",
                kind=IdentityKind.AGENT,
                status=IdentityStatus.ACTIVE,
                created_at=NOW,
            )
        self.messages: list[Message] = []
        self.cursor: Cursor | None = None

    def get_identity(self, identity_id: UUID):
        if self.actor is not None and self.actor.id == identity_id:
            return self.actor
        return None

    def get_membership(self, channel_id: UUID, identity_id: UUID):
        if (
            self.membership is not None
            and self.membership.channel_id == channel_id
            and self.membership.identity_id == identity_id
        ):
            return self.membership
        return None

    def append_message(self, command):
        message = Message(
            id=uuid4(),
            channel_id=command.channel_id,
            sequence=len(self.messages) + 1,
            sender_id=command.sender_id,
            kind=command.kind,
            body=command.body,
            created_at=NOW,
            parent_id=command.parent_id,
            idempotency_key=command.idempotency_key,
        )
        self.messages.append(message)
        return AppendResult(message=message, created=True)

    def read_messages(self, channel_id, *, after_sequence, limit):
        return [
            message
            for message in self.messages
            if message.channel_id == channel_id
            and message.sequence > after_sequence
        ][:limit]

    def record_delivery(self, channel_id, identity_id, sequence):
        acknowledged = (
            self.cursor.last_acknowledged_sequence if self.cursor is not None else 0
        )
        delivered = max(
            self.cursor.last_delivered_sequence if self.cursor is not None else 0,
            sequence,
        )
        self.cursor = Cursor(
            channel_id=channel_id,
            identity_id=identity_id,
            last_delivered_sequence=delivered,
            last_acknowledged_sequence=acknowledged,
        )
        return self.cursor

    def acknowledge(self, channel_id, identity_id, sequence):
        if self.cursor is None:
            self.cursor = Cursor(channel_id=channel_id, identity_id=identity_id)
        self.cursor = self.cursor.acknowledge(sequence)
        return self.cursor


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, **event) -> None:
        self.events.append(event)


def membership(
    actor_id: UUID, channel_id: UUID, *capabilities: Capability
) -> Membership:
    return Membership(
        channel_id=channel_id,
        identity_id=actor_id,
        role=MembershipRole.MEMBER,
        capabilities=frozenset(capabilities),
        joined_at=NOW,
    )


class DomainModelTests(TestCase):
    def test_message_requires_positive_sequence(self) -> None:
        with self.assertRaisesRegex(ValueError, "sequence must be positive"):
            Message(
                id=uuid4(),
                channel_id=uuid4(),
                sequence=0,
                sender_id=uuid4(),
                kind=MessageKind.TEXT,
                body="hello",
                created_at=NOW,
            )

    def test_timestamp_must_be_utc(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware UTC"):
            Message(
                id=uuid4(),
                channel_id=uuid4(),
                sequence=1,
                sender_id=uuid4(),
                kind=MessageKind.TEXT,
                body="hello",
                created_at=datetime(2026, 10, 10, 12, 0),
            )

    def test_cursor_cannot_acknowledge_undelivered_message(self) -> None:
        cursor = Cursor(
            channel_id=uuid4(), identity_id=uuid4(), last_delivered_sequence=3
        )
        with self.assertRaisesRegex(ValueError, "undelivered"):
            cursor.acknowledge(4)

    def test_cursors_never_move_backward(self) -> None:
        cursor = Cursor(
            channel_id=uuid4(),
            identity_id=uuid4(),
            last_delivered_sequence=5,
            last_acknowledged_sequence=3,
        )
        with self.assertRaisesRegex(ValueError, "delivered cursor cannot move backward"):
            cursor.record_delivery(4)
        with self.assertRaisesRegex(
            ValueError, "acknowledged cursor cannot move backward"
        ):
            cursor.acknowledge(2)


class BrokerServiceTests(TestCase):
    def setUp(self) -> None:
        self.actor_id = uuid4()
        self.channel_id = uuid4()
        self.audit = RecordingAudit()

    def test_send_requires_explicit_capability(self) -> None:
        repository = FakeRepository(
            membership(self.actor_id, self.channel_id, Capability.READ_MESSAGES)
        )
        service = BrokerService(repository, self.audit)

        with self.assertRaises(AuthorizationDenied):
            service.send_message(
                actor_id=self.actor_id,
                channel_id=self.channel_id,
                body="hello",
                correlation_id=uuid4(),
            )

        self.assertEqual([], repository.messages)
        self.assertEqual("denied", self.audit.events[0]["outcome"])

    def test_public_membership_does_not_grant_private_channel_access(self) -> None:
        public_channel_id = uuid4()
        repository = FakeRepository(
            membership(self.actor_id, public_channel_id, Capability.SEND_MESSAGES)
        )
        service = BrokerService(repository, self.audit)

        with self.assertRaises(AuthorizationDenied):
            service.send_message(
                actor_id=self.actor_id,
                channel_id=self.channel_id,
                body="private request",
                correlation_id=uuid4(),
            )

        self.assertEqual([], repository.messages)

    def test_send_and_read_share_domain_rules(self) -> None:
        repository = FakeRepository(
            membership(
                self.actor_id,
                self.channel_id,
                Capability.SEND_MESSAGES,
                Capability.READ_MESSAGES,
            )
        )
        service = BrokerService(repository, self.audit)
        sent = service.send_message(
            actor_id=self.actor_id,
            channel_id=self.channel_id,
            body="hello",
            correlation_id=uuid4(),
            idempotency_key="request-1",
        )
        read = service.read_messages(
            actor_id=self.actor_id,
            channel_id=self.channel_id,
            after_sequence=0,
            limit=10,
            correlation_id=uuid4(),
        )

        self.assertEqual((sent,), read)
        self.assertEqual(1, repository.cursor.last_delivered_sequence)
        self.assertEqual(["message.send", "message.read"], [
            event["action"] for event in self.audit.events
        ])

    def test_revoked_membership_has_no_authority(self) -> None:
        revoked = Membership(
            channel_id=self.channel_id,
            identity_id=self.actor_id,
            role=MembershipRole.MEMBER,
            capabilities=frozenset({Capability.SEND_MESSAGES}),
            joined_at=NOW,
            revoked_at=NOW,
        )
        service = BrokerService(FakeRepository(revoked), self.audit)

        with self.assertRaises(AuthorizationDenied):
            service.send_message(
                actor_id=self.actor_id,
                channel_id=self.channel_id,
                body="hello",
                correlation_id=uuid4(),
            )

    def test_revoked_identity_has_no_authority_with_active_membership(self) -> None:
        actor = Identity(
            id=self.actor_id,
            display_name="Revoked agent",
            kind=IdentityKind.AGENT,
            status=IdentityStatus.REVOKED,
            created_at=NOW,
        )
        repository = FakeRepository(
            membership(self.actor_id, self.channel_id, Capability.SEND_MESSAGES),
            actor=actor,
        )
        service = BrokerService(repository, self.audit)

        with self.assertRaises(AuthorizationDenied):
            service.send_message(
                actor_id=self.actor_id,
                channel_id=self.channel_id,
                body="hello",
                correlation_id=uuid4(),
            )

        self.assertEqual([], repository.messages)
        self.assertEqual("denied", self.audit.events[0]["outcome"])

    def test_read_limit_is_bounded_before_repository_access(self) -> None:
        repository = FakeRepository(
            membership(self.actor_id, self.channel_id, Capability.READ_MESSAGES)
        )
        service = BrokerService(repository, self.audit)

        with self.assertRaisesRegex(ValueError, "limit must be between"):
            service.read_messages(
                actor_id=self.actor_id,
                channel_id=self.channel_id,
                after_sequence=0,
                limit=101,
                correlation_id=uuid4(),
            )

    def test_acknowledgement_cannot_claim_an_undelivered_sequence(self) -> None:
        repository = FakeRepository(
            membership(
                self.actor_id,
                self.channel_id,
                Capability.ACKNOWLEDGE_MESSAGES,
            )
        )
        service = BrokerService(repository, self.audit)

        with self.assertRaisesRegex(ValueError, "undelivered"):
            service.acknowledge(
                actor_id=self.actor_id,
                channel_id=self.channel_id,
                acknowledged_sequence=1,
                correlation_id=uuid4(),
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
