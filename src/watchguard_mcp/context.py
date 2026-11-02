"""Request-scoped credential and request-id storage.

One container instance serves many tenants concurrently. Credentials must
never live in a global or module-level variable -- that would leak one
tenant's WatchGuard access into another tenant's request. A ContextVar is
set by the middleware at the start of each request and reset in `finally`,
so each asyncio task only ever sees its own request's credentials.

The request id below follows the same pattern: `run_tool` (tools/_common.py)
generates one per tool call so `WatchguardClient._send_raw` can tag its
vendor-call log lines with the same id, correlating "which tool call made
this outbound request" without threading an extra parameter through every
client method (PRD-21249 review round 1 must-fix, SOP SS6).
"""

from __future__ import annotations

import uuid
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


_request_id: ContextVar[str | None] = ContextVar("watchguard_request_id", default=None)


def new_request_id() -> str:
    """Generate a short id for one tool call (log-correlation only, not a secret)."""
    return uuid.uuid4().hex[:12]


def set_request_id(request_id: str) -> object:
    """Set the current tool call's request id; returns a reset token."""
    return _request_id.set(request_id)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


def get_request_id() -> str:
    """Read the current request id.

    Returns "unscoped" outside of `run_tool` (e.g. a test that calls
    `WatchguardClient` directly) rather than raising -- unlike credentials, a
    missing request id is a log-correlation gap, not a tenant-isolation bug.
    """
    return _request_id.get() or "unscoped"
