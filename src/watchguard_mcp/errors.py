"""Structured error envelope shared by every tool.

Tools never let an exception escape to the MCP layer -- every vendor-call
failure is caught and mapped to this fixed, finite error-code vocabulary so
the Agent can branch on `code` and decide whether `retryable` is worth
acting on.
"""

from __future__ import annotations

import json

# Fixed vocabulary -- do not invent new codes (SOP SS4.2).
ErrorCode = str

NOT_CONFIGURED = "not_configured"
UNAUTHORIZED = "unauthorized"
NOT_FOUND = "not_found"
INVALID_ARGUMENT = "invalid_argument"
RATE_LIMITED = "rate_limited"
UPSTREAM_ERROR = "upstream_error"

_RETRYABLE = {RATE_LIMITED, UPSTREAM_ERROR}


class WatchguardError(Exception):
    """Carries a structured error envelope through the tool layer."""

    def __init__(self, code: ErrorCode, message: str, *, retryable: bool | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = _RETRYABLE.issuperset({code}) if retryable is None else retryable

    def to_envelope(self) -> str:
        return json.dumps(
            {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}},
            ensure_ascii=False,
            separators=(",", ":"),
        )


def status_to_code(status_code: int) -> ErrorCode:
    """Map a WatchGuard HTTP status code to our fixed error vocabulary."""
    if status_code in (401, 403):
        return UNAUTHORIZED
    if status_code == 404:
        return NOT_FOUND
    if status_code in (400, 422):
        return INVALID_ARGUMENT
    if status_code == 429:
        return RATE_LIMITED
    if status_code >= 500:
        return UPSTREAM_ERROR
    return UPSTREAM_ERROR


def invalid_argument(message: str) -> WatchguardError:
    return WatchguardError(INVALID_ARGUMENT, message, retryable=False)


def not_configured(message: str) -> WatchguardError:
    return WatchguardError(NOT_CONFIGURED, message, retryable=False)
