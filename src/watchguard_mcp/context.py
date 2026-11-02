"""Request-scoped credential storage.

One container instance serves many tenants concurrently. Credentials must
never live in a global or module-level variable -- that would leak one
tenant's WatchGuard access into another tenant's request. A ContextVar is
set by the middleware at the start of each request and reset in `finally`,
so each asyncio task only ever sees its own request's credentials.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class WatchguardCredentials:
    access_id: str
    password: str
    api_key: str
    account_id: str | None = None


_credentials: ContextVar[WatchguardCredentials | None] = ContextVar(
    "watchguard_credentials", default=None
)


def set_credentials(credentials: WatchguardCredentials) -> object:
    """Set the current request's credentials; returns a reset token."""
    return _credentials.set(credentials)


def reset_credentials(token: object) -> None:
    _credentials.reset(token)  # type: ignore[arg-type]


def get_credentials() -> WatchguardCredentials:
    """Read the current request's credentials.

    Raises RuntimeError if called outside a request that went through the
    middleware -- that is a programming error, not a missing-header case
    (missing headers are rejected with 401 before a tool ever runs).
    """
    creds = _credentials.get()
    if creds is None:
        raise RuntimeError("No WatchGuard credentials in the current request context")
    return creds
