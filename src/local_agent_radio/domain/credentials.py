"""Channel-scoped bearer credentials for trusted local provisioning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import UUID, uuid4

from .errors import AuthorizationDenied
from .models import Channel, Identity


PUBLIC_CREDENTIAL_LIFETIME = timedelta(days=90)
_TOKEN_PREFIX = "lar_"


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class Credential:
    id: UUID
    identity_id: UUID
    channel_id: UUID
    secret_hash: bytes = field(repr=False)
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.secret_hash) != 32:
            raise ValueError("secret_hash must be a SHA-256 digest")
        _require_utc(self.created_at, "created_at")
        _require_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must follow created_at")
        if self.revoked_at is not None:
            _require_utc(self.revoked_at, "revoked_at")
            if self.revoked_at < self.created_at:
                raise ValueError("revoked_at cannot precede created_at")

    def usable_at(self, at: datetime) -> bool:
        _require_utc(at, "at")
        return self.revoked_at is None and self.created_at <= at < self.expires_at


def issue_public_credential(
    identity: Identity, channel: Channel
) -> tuple[Credential, str]:
    """Create a one-time token and a hash-only record for this channel."""
    secret = token_urlsafe(32)
    credential = Credential(
        id=uuid4(),
        identity_id=identity.id,
        channel_id=channel.id,
        secret_hash=sha256(secret.encode("ascii")).digest(),
        created_at=identity.created_at,
        expires_at=identity.created_at + PUBLIC_CREDENTIAL_LIFETIME,
    )
    return credential, f"{_TOKEN_PREFIX}{credential.id.hex}.{secret}"


def credential_id_and_secret(token: str) -> tuple[UUID, str]:
    """Parse the public lookup ID without exposing malformed token details."""
    if not isinstance(token, str) or len(token) > 200:
        raise AuthorizationDenied("invalid credential")
    lookup, separator, secret = token.partition(".")
    if not separator or not lookup.startswith(_TOKEN_PREFIX) or not secret:
        raise AuthorizationDenied("invalid credential")
    try:
        credential_id = UUID(hex=lookup[len(_TOKEN_PREFIX) :])
    except ValueError as error:
        raise AuthorizationDenied("invalid credential") from error
    return credential_id, secret


def secret_matches(credential: Credential, secret: str) -> bool:
    return compare_digest(
        credential.secret_hash, sha256(secret.encode("utf-8")).digest()
    )
