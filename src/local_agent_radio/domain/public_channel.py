"""Policy for the membership granted when an identity is registered."""

from __future__ import annotations

from datetime import datetime

from .models import (
    Capability,
    Channel,
    ChannelVisibility,
    Identity,
    IdentityKind,
    IdentityStatus,
    Membership,
    MembershipRole,
)


PUBLIC_CHANNEL_NAME = "public"
PUBLIC_MEMBER_CAPABILITIES = frozenset(
    {
        Capability.SEND_MESSAGES,
        Capability.READ_MESSAGES,
        Capability.ACKNOWLEDGE_MESSAGES,
        Capability.SEARCH_MESSAGES,
    }
)


def plan_public_membership(
    identity: Identity,
    channel: Channel,
    *,
    joined_at: datetime,
    existing: Membership | None = None,
) -> Membership | None:
    """Return the registration grant, or ``None`` if no new grant is allowed.

    Registration must store the identity and returned membership atomically.
    Existing memberships, including revoked ones, must be kept as they are.
    Following the channel is a separate client action.
    """
    if (
        channel.name != PUBLIC_CHANNEL_NAME
        or channel.visibility != ChannelVisibility.PUBLIC
    ):
        raise ValueError("expected the reserved public channel")
    if existing is not None:
        if existing.channel_id != channel.id or existing.identity_id != identity.id:
            raise ValueError("existing membership belongs to another identity or channel")
        return None
    if identity.status != IdentityStatus.ACTIVE or identity.kind not in {
        IdentityKind.HUMAN,
        IdentityKind.AGENT,
    }:
        return None
    membership = Membership(
        channel_id=channel.id,
        identity_id=identity.id,
        role=MembershipRole.MEMBER,
        capabilities=PUBLIC_MEMBER_CAPABILITIES,
        joined_at=joined_at,
    )
    if joined_at < identity.created_at or joined_at < channel.created_at:
        raise ValueError("membership cannot precede identity or channel creation")
    return membership
