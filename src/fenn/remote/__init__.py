"""Client-side remote execution helpers for the Fenn premium service.

This package is imported only when ``fenn run --host ...`` or ``fenn auth ...``
is invoked. Local execution (``fenn run main.py`` with no ``--host``) does not
touch any of these modules.
"""

from fenn.remote.client import RemoteClient
from fenn.remote.credentials import (
    DEFAULT_PROFILE,
    Credentials,
    load_credentials,
    resolve_api_key,
    write_credentials,
)
from fenn.remote.exceptions import (
    CredentialsError,
    InsufficientCreditsError,
    JobFailedError,
    RemoteError,
    WorkspaceTooLargeError,
)
from fenn.remote.workspace import pack_workspace

__all__ = [
    "RemoteClient",
    "Credentials",
    "CredentialsError",
    "DEFAULT_PROFILE",
    "load_credentials",
    "resolve_api_key",
    "write_credentials",
    "RemoteError",
    "InsufficientCreditsError",
    "JobFailedError",
    "WorkspaceTooLargeError",
    "pack_workspace",
]
