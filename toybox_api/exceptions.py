"""Exceptions for the ToyBox API client."""


class ToyBoxError(Exception):
    """Base exception for ToyBox API errors."""


class AuthenticationError(ToyBoxError):
    """Raised when authentication fails (invalid credentials)."""


class ConnectionError(ToyBoxError):
    """Raised when we can't connect to make.toys."""


class APIError(ToyBoxError):
    """Raised when the API returns an unexpected error."""


class SessionExpiredError(ToyBoxError):
    """Raised when the session/token has expired and re-auth is needed."""
