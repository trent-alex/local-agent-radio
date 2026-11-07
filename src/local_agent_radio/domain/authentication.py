"""Validate a channel-scoped token before a broker operation."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from .credentials import Credential, credential_id_and_secret, secret_matches
from .errors import AuthorizationDenied
from .models import Identity, IdentityStatus, Membership, utc_now


class CredentialRepository(Protocol):
    def get_credential(self, credential_id: UUID) -> Credential | None: ...

    def get_identity(self, identity_id: UUID) -> Identity | None: ...

    def get_membership(self, channel_id: UUID, identity_id: UUID) -> Membership | None: ...


class CredentialAuthenticator:
    """Resolve one token for the exact channel of the requested operation.

    The future transport adapter must call this for each request, record the
    authentication attempt, and pass the returned identity to BrokerService.
    """

    def __init__(self, repository: CredentialRepository) -> None:
        self._repository = repository

    def authenticate(
        self, *, token: str, channel_id: UUID, at: datetime | None = None
    ) -> Identity:
        credential_id, secret = credential_id_and_secret(token)
        credential = self._repository.get_credential(credential_id)
        if credential is None or not secret_matches(credential, secret):
            raise AuthorizationDenied("invalid credential")
        identity = self._repository.get_identity(credential.identity_id)
        membership = self._repository.get_membership(channel_id, credential.identity_id)
        if (
            credential.channel_id != channel_id
            or not credential.usable_at(at or utc_now())
            or identity is None
            or identity.status != IdentityStatus.ACTIVE
            or membership is None
            or not membership.active
        ):
            raise AuthorizationDenied("invalid credential")
        return identity
