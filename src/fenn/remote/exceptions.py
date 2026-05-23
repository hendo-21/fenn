"""Typed errors raised by the remote-execution client."""


class RemoteError(Exception):
    """Base class for all remote-execution client errors."""


class CredentialsError(RemoteError):
    """Raised when an API key cannot be resolved or the credentials file is malformed."""


class WorkspaceTooLargeError(RemoteError):
    """Raised when the project workspace exceeds the configured size cap."""


class InsufficientCreditsError(RemoteError):
    """Raised when the server returns 402 Payment Required."""


class JobFailedError(RemoteError):
    """Raised when a remote job ends in a non-success terminal state.

    Carries the final status string (``failed`` / ``cancelled``) and the
    job id so callers can re-fetch artifacts if they want to.
    """

    def __init__(self, message: str, job_id: str, status: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status = status
