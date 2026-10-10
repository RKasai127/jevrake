"""Exceptions raised by jevrake."""


class SchemaError(ValueError):
    """A field definition is invalid."""


class CoercionError(ValueError):
    """Candidate text cannot be converted to the target's type."""


class FetchError(Exception):
    """A page could not be fetched."""


class JevError(Exception):
    """A Jev request failed."""


class JevAuthError(JevError):
    """Authentication failed (missing key, 401, 403). The whole run should stop."""


class MissingAPIKeyError(JevAuthError):
    """The API key environment variable is not set."""
