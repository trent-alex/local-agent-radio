"""Trusted identity provisioning and automatic public membership."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from .credentials import Credential, issue_public_credential
from .models import Channel, Identity, IdentityKind, IdentityStatus, Membership, utc_now
from .public_channel import plan_public_membership


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    identity: Identity
    public_membership: Membership | None
    public_token: str | None = field(repr=False)


class RegistrationRepository(Protocol):
    """Storage operations available to trusted local provisioning code."""

    def get_public_channel(self) -> Channel: ...

    def save_registration(
        self,
        identity: Identity,
        public_membership: Membership | None,
        public_credential: Credential | None,
    ) -> None:
        """Commit identity, optional membership, and credential together."""
        ...


class RegistrationService:
    """Register an identity without starting a channel follow or moving a cursor.

    This is a trusted provisioning use case. A future CLI or HTTP adapter must
    authorize the operator before invoking it.
    """

    def __init__(self, repository: RegistrationRepository) -> None:
        self._repository = repository

    def register(
        self,
        *,
        display_name: str,
        kind: IdentityKind,
        identity_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> RegistrationResult:
        public_channel = self._repository.get_public_channel()
        identity = Identity(
            id=identity_id or uuid4(),
            display_name=display_name,
            kind=kind,
            status=IdentityStatus.ACTIVE,
            created_at=created_at or utc_now(),
        )
        membership = plan_public_membership(
            identity, public_channel, joined_at=identity.created_at
        )
        credential, token = (
            issue_public_credential(identity, public_channel)
            if membership is not None
            else (None, None)
        )
        self._repository.save_registration(identity, membership, credential)
        return RegistrationResult(
            identity=identity, public_membership=membership, public_token=token
        )
