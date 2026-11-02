"""Shared helpers for the tool modules.

Every tool: resolves which account it acts on (explicit arg > header >
credential-owner token claim, AC2/AC4), runs its vendor call, and returns
either the compact-JSON result or the structured error envelope -- never an
uncaught exception (SOP SS4.1) and never over the response-size cap (SS2.5).
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

from ..client import WatchguardAccessToken, WatchguardClient
from ..context import get_credentials, new_request_id, reset_request_id, set_request_id
from ..errors import WatchguardError
from ..logging_utils import log_event

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_RESPONSE_CHARS = 20_000


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def to_json(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= MAX_RESPONSE_CHARS:
        return text
    # The exact vendor response shape isn't confirmed without a live account
    # (see tech design "Open questions"), so we cannot safely truncate a
    # specific list field without risking emitting invalid JSON. Report the
    # overflow explicitly instead (SOP SS2.5: oversized results must be
    # truncated and the caller told explicitly).
    notice = {
        "truncated": True,
        "has_more": True,
        "message": (
            f"Result exceeded {MAX_RESPONSE_CHARS} characters and was omitted; "
            "retry with a smaller limit or a narrower filter."
        ),
    }
    return json.dumps(notice, ensure_ascii=False, separators=(",", ":"))


async def resolve_account(
    client: WatchguardClient, explicit_account_id: str | None
) -> tuple[str | None, WatchguardAccessToken]:
    header_account_id = get_credentials().account_id
    effective = explicit_account_id or header_account_id
    return await client.resolve_account_and_token(effective)


def require_account_id(account_id: str | None) -> str:
    if account_id:
        return account_id
    raise WatchguardError(
        "invalid_argument",
        "Could not determine a WatchGuard account id: no account id argument, no "
        "X-WatchGuard-Account-Id header, and the access token did not carry one. "
        "Pass an explicit account id.",
        retryable=False,
    )


def require_arg(value: str | None, name: str) -> str:
    if value:
        return value
    raise WatchguardError("invalid_argument", f"'{name}' is required", retryable=False)


async def run_tool(tool_name: str, body: Callable[[], Awaitable[dict[str, Any]]]) -> str:
    """Run one tool's body, logging a single structured `tool_call` line

    (request id, tool name, status, latency, and the mapped error code on
    failure -- never credentials or the result payload itself; PRD-21249
    review round 1 must-fix, SOP SS6). The request id is also published via
    `context.set_request_id` so `WatchguardClient._send_raw` can tag its own
    `vendor_call` log lines with it for the duration of this call.
    """
    request_id = new_request_id()
    token = set_request_id(request_id)
    started = time.monotonic()
    try:
        result = await body()
    except WatchguardError as exc:
        log_event(
            "tool_call",
            request_id=request_id,
            tool=tool_name,
            status="error",
            error_code=exc.code,
            latency_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return exc.to_envelope()
    finally:
        reset_request_id(token)
    log_event(
        "tool_call",
        request_id=request_id,
        tool=tool_name,
        status="ok",
        latency_ms=round((time.monotonic() - started) * 1000, 1),
    )
    return to_json(result)
