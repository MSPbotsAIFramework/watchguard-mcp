"""WatchGuard Cloud API client: OAuth token exchange, audience resolution,
retrying HTTP calls, and thin per-resource wrappers used by the tool layer.

Every call is made with the credentials carried on the *current* request
(see context.py) -- nothing here is cached across requests, per the
platform's request-isolation contract (PRD-21249 tech design, Decision 2).
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .context import WatchguardCredentials, get_request_id
from .errors import WatchguardError, status_to_code
from .logging_utils import log_event

CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 30.0
TOTAL_BUDGET_S = 110.0  # SOP SS5: single tool call (incl. retries) must stay < 120s
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 8.0
_RETRY_STATUS = {429, 500, 502, 503, 504}


async def _backoff_sleep(seconds: float) -> None:
    """Indirection so tests can mock out real waiting without touching the
    global asyncio module (retry/backoff timing tests patch this name)."""
    await asyncio.sleep(seconds)


def _decode_account_id_from_token(access_token: str) -> str | None:
    """Best-effort extraction of the owning account id from the bearer token.

    WatchGuard's documented token response (fetched 2026-11-02) only confirms
    `access_token` / `token_type` / `expires_in`; it does not confirm a JWT
    payload shape. This treats the token as an unverified JWT (we received it
    directly from the vendor's own token endpoint over TLS, so signature
    verification is not required for this purpose) and looks for a claim
    naming the account. Returns None if the token is not JWT-shaped or
    carries none of the claim names we check -- callers must then require an
    explicit account id. See tech design "Decisions made by DEV01" #6.
    """
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None
    for key in ("account_id", "accountId", "sub"):
        value = claims.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@dataclass
class WatchguardAccessToken:
    access_token: str
    account_id: str | None


class WatchguardClient:
    def __init__(self, credentials: WatchguardCredentials, base_url: str):
        self._credentials = credentials
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT_S, read=READ_TIMEOUT_S, write=READ_TIMEOUT_S, pool=READ_TIMEOUT_S),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "WatchguardClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # -- auth -----------------------------------------------------------

    async def resolve_audience(self, managed_account_id: str) -> str:
        """POST /v1/audiences -- resolve the audience for a managed (child) account."""
        resp = await self._send_raw(
            "POST",
            "/v1/audiences",
            headers=self._basic_auth_header(),
            json_body={"accountId": managed_account_id},
        )
        self._raise_for_status(resp)
        audience = resp.json().get("audience")
        if not audience:
            raise WatchguardError("upstream_error", "WatchGuard /v1/audiences response had no audience field", retryable=False)
        return audience

    async def get_access_token(self, *, audience: str | None) -> WatchguardAccessToken:
        """POST /oauth/token -- client-credentials grant, optionally scoped to `audience`."""
        body: dict[str, str] = {"grant_type": "client_credentials", "scope": "api-access"}
        if audience:
            body["audience"] = audience
        resp = await self._send_raw(
            "POST",
            "/oauth/token",
            headers=self._basic_auth_header(),
            form_body=body,
        )
        self._raise_for_status(resp)
        access_token = resp.json().get("access_token")
        if not access_token:
            raise WatchguardError("upstream_error", "WatchGuard /oauth/token response had no access_token field", retryable=False)
        return WatchguardAccessToken(
            access_token=access_token,
            account_id=_decode_account_id_from_token(access_token),
        )

    async def resolve_account_and_token(self, explicit_account_id: str | None) -> tuple[str | None, WatchguardAccessToken]:
        """Resolve which account a call should act on and get a scoped token.

        Explicit account id (tool arg or X-WatchGuard-Account-Id header) ->
        resolve its audience first (managed-account delegation, AC4).
        Otherwise -> request a token with no audience and try to read the
        owning account id back out of it (AC2); the id may come back None if
        the token does not carry one, in which case callers that need a
        concrete account id must ask the caller to supply one explicitly.
        """
        if explicit_account_id:
            audience = await self.resolve_audience(explicit_account_id)
            token = await self.get_access_token(audience=audience)
            return explicit_account_id, token
        token = await self.get_access_token(audience=None)
        return token.account_id, token

    def _basic_auth_header(self) -> dict[str, str]:
        raw = f"{self._credentials.access_id}:{self._credentials.password}".encode("utf-8")
        return {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}

    # -- generic retrying request ----------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: WatchguardAccessToken,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "WatchGuard-API-Key": self._credentials.api_key,
        }
        resp = await self._send_raw(method, path, headers=headers, params=params, json_body=json_body)
        self._raise_for_status(resp)
        if not resp.content:
            return {}
        return resp.json()

    async def _send_raw(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, str] | None = None,
    ) -> httpx.Response:
        # One `vendor_call` log line per attempt (method, path, status/outcome,
        # latency -- never headers, since those carry the bearer token and API
        # key). `request_id` ties these lines back to the `run_tool` call that
        # triggered them (PRD-21249 review round 1 must-fix, SOP SS6).
        request_id = get_request_id()
        deadline = time.monotonic() + TOTAL_BUDGET_S
        last_response: httpx.Response | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                resp = await self._http.request(
                    method,
                    path,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=form_body,
                )
            except httpx.TimeoutException as exc:
                log_event(
                    "vendor_call",
                    request_id=request_id,
                    method=method,
                    path=path,
                    attempt=attempt,
                    status="timeout",
                    latency_ms=round((time.monotonic() - started) * 1000, 1),
                )
                if attempt == MAX_ATTEMPTS or time.monotonic() >= deadline:
                    raise WatchguardError("upstream_error", f"WatchGuard request timed out: {exc}", retryable=True) from exc
                await _backoff_sleep(min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_CAP_S))
                continue
            except httpx.HTTPError as exc:
                log_event(
                    "vendor_call",
                    request_id=request_id,
                    method=method,
                    path=path,
                    attempt=attempt,
                    status="network_error",
                    latency_ms=round((time.monotonic() - started) * 1000, 1),
                )
                if attempt == MAX_ATTEMPTS or time.monotonic() >= deadline:
                    raise WatchguardError("upstream_error", f"WatchGuard request failed: {exc}", retryable=True) from exc
                await _backoff_sleep(min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_CAP_S))
                continue

            log_event(
                "vendor_call",
                request_id=request_id,
                method=method,
                path=path,
                attempt=attempt,
                status_code=resp.status_code,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
            )
            last_response = resp
            if resp.status_code not in _RETRY_STATUS:
                return resp
            if attempt == MAX_ATTEMPTS or time.monotonic() >= deadline:
                return resp
            await _backoff_sleep(self._retry_delay(resp, attempt))
        assert last_response is not None
        return last_response

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), BACKOFF_CAP_S)
            except ValueError:
                pass
        return min(BACKOFF_BASE_S * (2 ** (attempt - 1)), BACKOFF_CAP_S)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        code = status_to_code(resp.status_code)
        message = f"WatchGuard API returned HTTP {resp.status_code}"
        try:
            body = resp.json()
            detail = body.get("message") or body.get("error") or body.get("detail")
            if isinstance(detail, str) and detail:
                message = detail
        except Exception:
            pass
        raise WatchguardError(code, message)

    # -- Accounts (v2) -----------------------------------------------------

    async def get_account(self, token: WatchguardAccessToken, account_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/v2/accounts/{account_id}", token=token)

    async def list_child_accounts(
        self, token: WatchguardAccessToken, account_id: str, *, limit: int, cursor: str | None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self.request("GET", f"/v2/accounts/{account_id}/children", token=token, params=params)

    async def create_account(self, token: WatchguardAccessToken, parent_account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/v2/accounts/{parent_account_id}", token=token, json_body=payload)

    async def update_account(self, token: WatchguardAccessToken, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", f"/v2/accounts/{account_id}", token=token, json_body=payload)

    async def delete_account(self, token: WatchguardAccessToken, account_id: str) -> dict[str, Any]:
        return await self.request("DELETE", f"/v2/accounts/{account_id}", token=token)

    # -- Activations (v1) ---------------------------------------------------

    async def activate_device(self, token: WatchguardAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/v1/activate", token=token, json_body=payload)

    async def list_recent_activations(self, token: WatchguardAccessToken, *, limit: int) -> dict[str, Any]:
        return await self.request("GET", "/v1/recentactivations", token=token, params={"limit": limit})

    async def get_activation_batch_status(self, token: WatchguardAccessToken, batch_id: str) -> dict[str, Any]:
        # The vendor documents this as a PUT even though it only reads status.
        return await self.request("PUT", f"/v1/activationbatchstatuses/{batch_id}", token=token)

    # -- Allocations (v2, read-only in v1) -----------------------------------

    async def get_allocation_summary(self, token: WatchguardAccessToken, account_id: str, resource_type: str) -> dict[str, Any]:
        return await self.request("GET", f"/v2/{account_id}/assets/summary/{resource_type}", token=token)

    async def list_allocations(
        self, token: WatchguardAccessToken, account_id: str, resource_type: str, *, limit: int
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/v2/{account_id}/assets/allocations/{resource_type}", token=token, params={"limit": limit}
        )

    async def list_account_licenses(
        self, token: WatchguardAccessToken, account_id: str, resource_type: str, *, limit: int
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/v2/{account_id}/assets/licenses/{resource_type}", token=token, params={"limit": limit}
        )

    async def list_assigned_assets(
        self, token: WatchguardAccessToken, account_id: str, resource_type: str, *, limit: int
    ) -> dict[str, Any]:
        return await self.request(
            "GET", f"/v2/{account_id}/assets/assigned/{resource_type}", token=token, params={"limit": limit}
        )

    # -- Operator Management (v1) --------------------------------------------

    async def create_operator(self, token: WatchguardAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/v1/operators", token=token, json_body=payload)

    async def update_operator(self, token: WatchguardAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", "/v1/operators", token=token, json_body=payload)

    async def delete_operator(self, token: WatchguardAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        # The vendor exposes delete as POST /v1/DeleteOperators, not a DELETE
        # verb (tech design Decision 5): kept as a faithful 1:1 mapping.
        return await self.request("POST", "/v1/DeleteOperators", token=token, json_body=payload)

    async def list_operators_by_account(self, token: WatchguardAccessToken, account_id: str, *, limit: int) -> dict[str, Any]:
        return await self.request(
            "GET", "/v1/OperatorsByAccountId", token=token, params={"accountId": account_id, "limit": limit}
        )

    async def get_operator_transaction_status(self, token: WatchguardAccessToken, transaction_id: str) -> dict[str, Any]:
        return await self.request("GET", "/v1/TransactionStatus", token=token, params={"transaction_id": transaction_id})
