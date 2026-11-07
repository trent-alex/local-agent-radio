import sqlite3
import stat
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from uuid import uuid4

from local_agent_radio.domain import (
    AuthorizationDenied,
    Capability,
    ChannelVisibility,
    CredentialAuthenticator,
    IdentityKind,
    RegistrationService,
)
from local_agent_radio.domain.credentials import (
    PUBLIC_CREDENTIAL_LIFETIME,
    credential_id_and_secret,
)
from local_agent_radio.storage import SqliteRegistrationRepository


class RegistrationStorageTests(TestCase):
    def setUp(self) -> None:
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.database_path = Path(temporary_directory.name) / "radio.sqlite3"
        self.repository = SqliteRegistrationRepository(self.database_path)
        self.public = self.repository.initialize()
        self.service = RegistrationService(self.repository)
        self.authenticator = CredentialAuthenticator(self.repository)

    def test_initialization_keeps_one_reserved_public_channel(self) -> None:
        again = SqliteRegistrationRepository(self.database_path).initialize()
        self.assertEqual(self.public, again)
        self.assertEqual("public", again.name)
        self.assertEqual(ChannelVisibility.PUBLIC, again.visibility)
        with sqlite3.connect(self.database_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        self.assertEqual(1, count)
        self.assertEqual(0o600, stat.S_IMODE(self.database_path.stat().st_mode))

    def test_agent_registration_persists_limited_membership_after_reopen(self) -> None:
        registered = self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)
        reopened = SqliteRegistrationRepository(self.database_path)

        self.assertEqual(
            registered.identity, reopened.get_identity(registered.identity.id)
        )
        membership = reopened.get_membership(self.public.id, registered.identity.id)
        self.assertEqual(registered.public_membership, membership)
        self.assertTrue(membership.permits(Capability.SEND_MESSAGES))
        self.assertTrue(membership.permits(Capability.READ_MESSAGES))
        self.assertFalse(membership.permits(Capability.ADMINISTER_CHANNEL))
        self.assertFalse(membership.permits(Capability.READ_ARTIFACTS))
        self.assertIsNotNone(registered.public_token)

    def test_public_token_is_scoped_and_only_its_hash_is_stored(self) -> None:
        registered = self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)
        credential_id, secret = credential_id_and_secret(registered.public_token)
        saved = self.repository.get_credential(credential_id)

        self.assertEqual(registered.identity.id, saved.identity_id)
        self.assertEqual(self.public.id, saved.channel_id)
        self.assertEqual(sha256(secret.encode("ascii")).digest(), saved.secret_hash)
        self.assertNotIn(secret, repr(saved))
        self.assertNotIn(registered.public_token, repr(registered))
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT secret_hash FROM credentials WHERE id = ?",
                (str(credential_id),),
            ).fetchone()
        self.assertEqual(saved.secret_hash, row[0])
        self.assertNotIn(registered.public_token.encode(), self.database_path.read_bytes())

        authenticated = self.authenticator.authenticate(
            token=registered.public_token, channel_id=self.public.id
        )
        self.assertEqual(registered.identity, authenticated)

    def test_public_token_cannot_authenticate_to_private_channel_even_if_invited(self) -> None:
        registered = self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)
        private_channel_id = uuid4()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                "INSERT INTO channels (id, name, visibility, created_at) "
                "VALUES (?, ?, 'private', ?)",
                (str(private_channel_id), "private-work", registered.identity.created_at.isoformat()),
            )
            connection.execute(
                "INSERT INTO channel_memberships "
                "(channel_id, identity_id, role, capabilities, joined_at) "
                "VALUES (?, ?, 'member', '[\"read_messages\"]', ?)",
                (
                    str(private_channel_id),
                    str(registered.identity.id),
                    registered.identity.created_at.isoformat(),
                ),
            )

        with self.assertRaises(AuthorizationDenied):
            self.authenticator.authenticate(
                token=registered.public_token, channel_id=private_channel_id
            )

    def test_tampered_expired_and_revoked_public_token_is_denied(self) -> None:
        registered = self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)
        token = registered.public_token
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        for invalid_token in (tampered, "not-a-radio-token"):
            with self.subTest(token=invalid_token):
                with self.assertRaises(AuthorizationDenied):
                    self.authenticator.authenticate(
                        token=invalid_token, channel_id=self.public.id
                    )

        with self.assertRaises(AuthorizationDenied):
            self.authenticator.authenticate(
                token=token,
                channel_id=self.public.id,
                at=registered.identity.created_at + PUBLIC_CREDENTIAL_LIFETIME,
            )
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE credentials SET revoked_at = created_at WHERE identity_id = ?",
                (str(registered.identity.id),),
            )
        with self.assertRaises(AuthorizationDenied):
            self.authenticator.authenticate(token=token, channel_id=self.public.id)

    def test_revoked_identity_or_membership_blocks_valid_token(self) -> None:
        for table, update in (
            ("identities", "UPDATE identities SET status = 'revoked' WHERE id = ?"),
            (
                "channel_memberships",
                "UPDATE channel_memberships SET revoked_at = joined_at WHERE identity_id = ?",
            ),
        ):
            with self.subTest(table=table):
                registered = self.service.register(
                    display_name=f"Agent {table}", kind=IdentityKind.AGENT
                )
                with sqlite3.connect(self.database_path) as connection:
                    connection.execute(update, (str(registered.identity.id),))
                with self.assertRaises(AuthorizationDenied):
                    self.authenticator.authenticate(
                        token=registered.public_token, channel_id=self.public.id
                    )

    def test_critic_registration_does_not_grant_public_membership(self) -> None:
        registered = self.service.register(display_name="Critic", kind=IdentityKind.CRITIC)
        self.assertIsNone(registered.public_membership)
        self.assertIsNone(registered.public_token)
        self.assertIsNotNone(self.repository.get_identity(registered.identity.id))
        self.assertIsNone(
            self.repository.get_membership(self.public.id, registered.identity.id)
        )

    def test_failed_membership_write_rolls_back_identity(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "CREATE TRIGGER reject_membership BEFORE INSERT ON channel_memberships "
                "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
            )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "simulated write failure"):
            self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)

        with sqlite3.connect(self.database_path) as connection:
            identities = connection.execute("SELECT COUNT(*) FROM identities").fetchone()[0]
            memberships = connection.execute(
                "SELECT COUNT(*) FROM channel_memberships"
            ).fetchone()[0]
        self.assertEqual((0, 0), (identities, memberships))

    def test_failed_credential_write_rolls_back_identity_and_membership(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "CREATE TRIGGER reject_credential BEFORE INSERT ON credentials "
                "BEGIN SELECT RAISE(ABORT, 'simulated credential failure'); END"
            )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "simulated credential failure"):
            self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)

        with sqlite3.connect(self.database_path) as connection:
            counts = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("identities", "channel_memberships", "credentials")
            )
        self.assertEqual((0, 0, 0), counts)

    def test_version_one_store_upgrades_without_losing_membership(self) -> None:
        registered = self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("DROP TABLE credentials")
            connection.execute("PRAGMA user_version = 1")

        self.repository.initialize()

        self.assertEqual(
            registered.identity, self.repository.get_identity(registered.identity.id)
        )
        self.assertEqual(
            registered.public_membership,
            self.repository.get_membership(self.public.id, registered.identity.id),
        )
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(2, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM credentials").fetchone()[0])

    def test_reinitialize_does_not_restore_revoked_membership(self) -> None:
        registered = self.service.register(display_name="Agent A", kind=IdentityKind.AGENT)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE channel_memberships SET revoked_at = joined_at "
                "WHERE channel_id = ? AND identity_id = ?",
                (str(self.public.id), str(registered.identity.id)),
            )

        self.repository.initialize()
        membership = self.repository.get_membership(
            self.public.id, registered.identity.id
        )
        self.assertFalse(membership.active)
        self.assertFalse(membership.permits(Capability.READ_MESSAGES))
