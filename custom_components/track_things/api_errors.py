"""Safe errors: never retain URLs, credentials, response messages, or entry bodies."""


class ApiError(Exception):
    """Base error whose public attributes are safe to log."""

    def __init__(
        self,
        status: int | None = None,
        *,
        code: str = "request_failed",
        retry_after: float | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Track Things {code}" + (f" (HTTP {status})" if status else ""))


class AuthenticationError(ApiError):
    """Credentials must be refreshed or replaced."""


class PermissionDeniedError(ApiError):
    """The authenticated account cannot access the resource."""


class NotFoundError(ApiError):
    """The requested resource is absent."""


class ConflictError(ApiError):
    """A schema guard or idempotency conflict requires caller intervention."""


class RateLimitError(ApiError):
    """The backend asked the caller to wait."""


class ServerError(ApiError):
    """The backend is temporarily unavailable."""


class TransportError(ApiError):
    """Connection or response transport failed; a write outcome may be unknown."""


class ApiTimeoutError(TransportError):
    """The request timed out; a write outcome may be unknown."""


class InvalidResponseError(ApiError):
    """The server did not return the expected wire contract."""
