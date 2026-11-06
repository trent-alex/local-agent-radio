from datetime import UTC, datetime, timedelta
from unittest import TestCase
from uuid import uuid4

from local_agent_radio.domain import (
    Capability,
    Channel,
    ChannelVisibility,
    Identity,
    IdentityKind,
    IdentityStatus,
    Membership,
    MembershipRole,
    plan_public_membership,
)


NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def public_channel() -> Channel:
    return Channel(
        id=uuid4(),
        name="public",
        created_at=NOW - timedelta(minutes=1),
        visibility=ChannelVisibility.PUBLIC,
    )


def identity(
    kind: IdentityKind, status: IdentityStatus = IdentityStatus.ACTIVE
) -> Identity:
    return Identity(
        id=uuid4(),
        display_name="Participant",
        kind=kind,
        status=status,
        created_at=NOW,
    )


class PublicMembershipPolicyTests(TestCase):
    def test_active_agents_and_humans_receive_only_message_capabilities(self) -> None:
        channel = public_channel()
        expected = frozenset(
            {
                Capability.SEND_MESSAGES,
                Capability.READ_MESSAGES,
                Capability.ACKNOWLEDGE_MESSAGES,
                Capability.SEARCH_MESSAGES,
            }
        )
        for kind in (IdentityKind.AGENT, IdentityKind.HUMAN):
            with self.subTest(kind=kind):
                actor = identity(kind)
                membership = plan_public_membership(actor, channel, joined_at=NOW)
                self.assertIsNotNone(membership)
                self.assertEqual(channel.id, membership.channel_id)
                self.assertEqual(actor.id, membership.identity_id)
                self.assertEqual(MembershipRole.MEMBER, membership.role)
                self.assertEqual(expected, membership.capabilities)
                self.assertNotIn(Capability.READ_ARTIFACTS, membership.capabilities)
                self.assertNotIn(Capability.ADMINISTER_CHANNEL, membership.capabilities)

    def test_critics_and_revoked_identities_receive_no_automatic_grant(self) -> None:
        channel = public_channel()
        for actor in (
            identity(IdentityKind.CRITIC),
            identity(IdentityKind.AGENT, IdentityStatus.REVOKED),
        ):
            with self.subTest(kind=actor.kind, status=actor.status):
                self.assertIsNone(plan_public_membership(actor, channel, joined_at=NOW))

    def test_existing_revoked_membership_is_not_restored(self) -> None:
        channel = public_channel()
        actor = identity(IdentityKind.AGENT)
        revoked = Membership(
            channel_id=channel.id,
            identity_id=actor.id,
            role=MembershipRole.MEMBER,
            capabilities=frozenset({Capability.READ_MESSAGES}),
            joined_at=NOW,
            revoked_at=NOW,
        )
        self.assertIsNone(
            plan_public_membership(actor, channel, joined_at=NOW, existing=revoked)
        )
        self.assertFalse(revoked.permits(Capability.READ_MESSAGES))

    def test_private_or_misnamed_channel_cannot_receive_public_grant(self) -> None:
        actor = identity(IdentityKind.AGENT)
        for channel in (
            Channel(id=uuid4(), name="private", created_at=NOW),
            Channel(
                id=uuid4(),
                name="other",
                created_at=NOW,
                visibility=ChannelVisibility.PUBLIC,
            ),
        ):
            with self.subTest(channel=channel):
                with self.assertRaisesRegex(ValueError, "reserved public channel"):
                    plan_public_membership(actor, channel, joined_at=NOW)
