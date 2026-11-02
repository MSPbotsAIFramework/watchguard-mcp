"""Per-request credential extraction.

Reads the WatchGuard credential headers, rejects the request with 401 (not
500, not a silent environment-variable fallback) if any required header is
missing, and stores the credentials in a request-scoped ContextVar for the
duration of the request only (SOP SS3.1/SS3.2).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .context import WatchguardCredentials, reset_credentials, set_credentials

# header (lowercase, Starlette normalizes lookups case-insensitively) -> the
# name we show back to the caller when it's missing.
REQUIRED_HEADERS = {
    "x-watchguard-access-id": "X-WatchGuard-Access-Id",
    "x-watchguard-password": "X-WatchGuard-Password",
    "x-watchguard-api-key": "X-WatchGuard-Api-Key",
}
ACCOUNT_HEADER = "x-watchguard-account-id"
MCP_PATH = "/mcp"


class CredentialsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path != MCP_PATH:
            return await call_next(request)

        missing = [name for header, name in REQUIRED_HEADERS.items() if not request.headers.get(header)]
        if missing:
            return JSONResponse(
                {"error": "missing required header(s)", "missing_headers": missing},
                status_code=401,
            )

        credentials = WatchguardCredentials(
            access_id=request.headers["x-watchguard-access-id"],
            password=request.headers["x-watchguard-password"],
            api_key=request.headers["x-watchguard-api-key"],
            account_id=request.headers.get(ACCOUNT_HEADER) or None,
        )
        token = set_credentials(credentials)
        try:
            return await call_next(request)
        finally:
            reset_credentials(token)
