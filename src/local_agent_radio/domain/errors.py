"""Errors expressed in domain terms rather than transport terms."""


class DomainError(Exception):
    """Base class for expected domain failures."""


class AuthorizationDenied(DomainError):
    """The authenticated actor lacks authority for an operation."""


class NotFound(DomainError):
    """A requested domain entity does not exist or is not visible to the actor."""


class IdempotencyConflict(DomainError):
    """An idempotency key was reused with a different request payload."""
