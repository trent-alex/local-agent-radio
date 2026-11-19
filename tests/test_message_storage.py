import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from local_agent_radio.domain import (
    BrokerService,
    CredentialAuthenticator,
    IdentityKind,
    IdempotencyConflict,
    MessageKind,
    NotFound,
    RegistrationService,
)
from local_agent_radio.domain.ports import AppendMessage
from local_agent_radio.storage import SqliteRegistrationRepository


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, **event) -> None:
        self.events.append(event)


class MessageStorageTests(TestCase):
    def setUp(self) -> None:
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.database_path = Path(temporary_directory.name) / "radio.sqlite3"
        self.repository = SqliteRegistrationRepository(self.database_path)
        self.public = self.repository.initialize()
        self.registered = RegistrationService(self.repository).register(
            display_name="Agent A", kind=IdentityKind.AGENT
        )
        self.actor = CredentialAuthenticator(self.repository).authenticate(
            token=self.registered.public_token, channel_id=self.public.id
        )
        self.audit = RecordingAudit()
        self.service = BrokerService(self.repository, self.audit)

    def send_request(self, *, idempotency_key: str | None = None):
        return self.service.send_message(
            actor_id=self.actor.id,
            channel_id=self.public.id,
            kind=MessageKind.REQUEST,
            body="Can another agent review this plan?",
            correlation_id=uuid4(),
            idempotency_key=idempotency_key,
        )

    def test_public_request_survives_reopening_sqlite(self) -> None:
        sent = self.send_request()
        reopened = SqliteRegistrationRepository(self.database_path)
        found = reopened.read_messages(self.public.id, after_sequence=0, limit=10)

        self.assertEqual((sent,), found)
        self.assertEqual(1, sent.sequence)
        self.assertEqual(MessageKind.REQUEST, sent.kind)
        self.assertEqual(self.actor.id, sent.sender_id)

    def test_retry_returns_original_message_and_changed_payload_conflicts(self) -> None:
        first = self.send_request(idempotency_key="request-1")
        again = self.send_request(idempotency_key="request-1")

        self.assertEqual(first, again)
        self.assertEqual(
            ["created", "replayed"],
            [event["outcome"] for event in self.audit.events],
        )
        with self.assertRaises(IdempotencyConflict):
            self.service.send_message(
                actor_id=self.actor.id,
                channel_id=self.public.id,
                kind=MessageKind.REQUEST,
                body="A different request",
                correlation_id=uuid4(),
                idempotency_key="request-1",
            )
        self.assertEqual(
            (first,), self.repository.read_messages(self.public.id, after_sequence=0, limit=10)
        )

    def test_second_agent_can_reply_with_parent_link_and_next_sequence(self) -> None:
        request = self.send_request()
        second = RegistrationService(self.repository).register(
            display_name="Agent B", kind=IdentityKind.AGENT
        )
        second_actor = CredentialAuthenticator(self.repository).authenticate(
            token=second.public_token, channel_id=self.public.id
        )
        reply = self.service.send_message(
            actor_id=second_actor.id,
            channel_id=self.public.id,
            kind=MessageKind.TEXT,
            body="I can review it.",
            parent_id=request.id,
            correlation_id=uuid4(),
        )

        self.assertEqual(request.id, reply.parent_id)
        self.assertEqual(2, reply.sequence)
        reopened = SqliteRegistrationRepository(self.database_path)
        self.assertEqual(
            (reply,), reopened.read_messages(self.public.id, after_sequence=1, limit=10)
        )

    def test_parent_from_another_channel_is_rejected(self) -> None:
        request = self.send_request()
        private_id = uuid4()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO channels (id, name, visibility, created_at) "
                "VALUES (?, 'private-work', 'private', ?)",
                (str(private_id), self.actor.created_at.isoformat()),
            )

        with self.assertRaises(NotFound):
            self.repository.append_message(
                AppendMessage(
                    channel_id=private_id,
                    sender_id=self.actor.id,
                    kind=MessageKind.TEXT,
                    body="Wrong channel",
                    parent_id=request.id,
                    idempotency_key=None,
                )
            )
        self.assertEqual(
            (), self.repository.read_messages(private_id, after_sequence=0, limit=10)
        )

    def test_version_two_database_gains_message_table(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("DROP TABLE messages")
            connection.execute("PRAGMA user_version = 2")

        self.repository.initialize()

        actor = CredentialAuthenticator(self.repository).authenticate(
            token=self.registered.public_token, channel_id=self.public.id
        )
        self.assertEqual(self.actor, actor)
        sent = self.send_request()
        self.assertEqual(1, sent.sequence)
