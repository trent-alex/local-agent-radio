import sqlite3
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from local_agent_radio.domain import (
    Capability,
    ChannelVisibility,
    IdentityKind,
    RegistrationService,
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

    def test_critic_registration_does_not_grant_public_membership(self) -> None:
        registered = self.service.register(display_name="Critic", kind=IdentityKind.CRITIC)
        self.assertIsNone(registered.public_membership)
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
