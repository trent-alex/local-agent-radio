"""Small SQLite registration store; later broker storage builds on this schema."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from local_agent_radio.domain.models import (
    Capability,
    Channel,
    ChannelVisibility,
    Identity,
    IdentityKind,
    IdentityStatus,
    Membership,
    MembershipRole,
    utc_now,
)
from local_agent_radio.domain.public_channel import PUBLIC_CHANNEL_NAME


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    visibility TEXT NOT NULL CHECK (visibility IN ('private', 'public')),
    created_at TEXT NOT NULL,
    CHECK (name != 'public' OR visibility = 'public')
);
CREATE TABLE IF NOT EXISTS identities (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('human', 'agent', 'critic')),
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_memberships (
    channel_id TEXT NOT NULL REFERENCES channels(id),
    identity_id TEXT NOT NULL REFERENCES identities(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'critic')),
    capabilities TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (channel_id, identity_id)
);
"""


class SqliteRegistrationRepository:
    """Owns the reserved channel and atomic identity/member writes.

    This adapter intentionally exposes no registration endpoint or credential.
    Its caller must be trusted provisioning code.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        # sqlite3.connect creates new files using the process umask, which may
        # leave identity data readable by other local users.
        try:
            descriptor = os.open(
                self.database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> Channel:
        """Create the initial schema and the one reserved public channel."""
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version > 1:
                    raise RuntimeError(f"unsupported database version {version}")
                for statement in _SCHEMA.strip().split(";\n"):
                    statement = statement.strip().rstrip(";")
                    if statement:
                        connection.execute(statement)
                row = connection.execute(
                    "SELECT * FROM channels WHERE name = ?", (PUBLIC_CHANNEL_NAME,)
                ).fetchone()
                if row is None:
                    channel = Channel(
                        id=uuid4(),
                        name=PUBLIC_CHANNEL_NAME,
                        visibility=ChannelVisibility.PUBLIC,
                        created_at=utc_now(),
                    )
                    connection.execute(
                        "INSERT INTO channels (id, name, visibility, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            str(channel.id),
                            channel.name,
                            channel.visibility.value,
                            channel.created_at.isoformat(),
                        ),
                    )
                else:
                    channel = self._channel(row)
                    if channel.visibility != ChannelVisibility.PUBLIC:
                        raise RuntimeError("reserved public channel has wrong visibility")
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
                return channel
            except Exception:
                connection.rollback()
                raise

    def get_public_channel(self) -> Channel:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM channels WHERE name = ?", (PUBLIC_CHANNEL_NAME,)
            ).fetchone()
        if row is None:
            raise RuntimeError("registration store has not been initialized")
        channel = self._channel(row)
        if channel.visibility != ChannelVisibility.PUBLIC:
            raise RuntimeError("reserved public channel has wrong visibility")
        return channel

    def save_registration(
        self, identity: Identity, public_membership: Membership | None
    ) -> None:
        """A membership insert failure also rolls back the identity insert."""
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO identities (id, display_name, kind, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        str(identity.id),
                        identity.display_name,
                        identity.kind.value,
                        identity.status.value,
                        identity.created_at.isoformat(),
                    ),
                )
                if public_membership is not None:
                    connection.execute(
                        "INSERT INTO channel_memberships "
                        "(channel_id, identity_id, role, capabilities, joined_at, revoked_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            str(public_membership.channel_id),
                            str(public_membership.identity_id),
                            public_membership.role.value,
                            json.dumps(
                                sorted(
                                    capability.value
                                    for capability in public_membership.capabilities
                                )
                            ),
                            public_membership.joined_at.isoformat(),
                            (
                                public_membership.revoked_at.isoformat()
                                if public_membership.revoked_at is not None
                                else None
                            ),
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get_identity(self, identity_id: UUID) -> Identity | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM identities WHERE id = ?", (str(identity_id),)
            ).fetchone()
        if row is None:
            return None
        return Identity(
            id=UUID(row["id"]),
            display_name=row["display_name"],
            kind=IdentityKind(row["kind"]),
            status=IdentityStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_membership(
        self, channel_id: UUID, identity_id: UUID
    ) -> Membership | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM channel_memberships "
                "WHERE channel_id = ? AND identity_id = ?",
                (str(channel_id), str(identity_id)),
            ).fetchone()
        if row is None:
            return None
        return Membership(
            channel_id=UUID(row["channel_id"]),
            identity_id=UUID(row["identity_id"]),
            role=MembershipRole(row["role"]),
            capabilities=frozenset(
                Capability(value) for value in json.loads(row["capabilities"])
            ),
            joined_at=datetime.fromisoformat(row["joined_at"]),
            revoked_at=(
                datetime.fromisoformat(row["revoked_at"])
                if row["revoked_at"] is not None
                else None
            ),
        )

    @staticmethod
    def _channel(row: sqlite3.Row) -> Channel:
        return Channel(
            id=UUID(row["id"]),
            name=row["name"],
            visibility=ChannelVisibility(row["visibility"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
