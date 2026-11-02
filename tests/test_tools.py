"""tools/list snapshot, account resolution, error-envelope mapping, and
destructive-tool behavior. Everything here mocks the vendor API with respx --
no live WatchGuard account needed (TC1, TC2, TC4, TC5, TC6, TC7)."""

from __future__ import annotations

import base64
import json

import pytest
import respx
from fastmcp import Client
from httpx import Response

import watchguard_mcp.client as client_module
from watchguard_mcp.context import WatchguardCredentials, reset_credentials, set_credentials
from watchguard_mcp.server import build_mcp
from watchguard_mcp.settings import Settings

BASE_URL = "https://api.usa.cloud.watchguard.com"

EXPECTED_TOOL_NAMES = {
    "watchguard_get_account",
    "watchguard_list_child_accounts",
    "watchguard_create_account",
    "watchguard_update_account",
    "watchguard_delete_account",
    "watchguard_activate_device",
    "watchguard_list_recent_activations",
    "watchguard_get_activation_batch_status",
    "watchguard_get_allocation_summary",
    "watchguard_list_allocations",
    "watchguard_list_account_licenses",
    "watchguard_list_assigned_assets",
    "watchguard_create_operator",
    "watchguard_update_operator",
    "watchguard_delete_operator",
    "watchguard_list_operators_by_account",
    "watchguard_get_operator_transaction_status",
}


def _fake_jwt(claims: dict) -> str:
    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


@pytest.fixture
def mcp():
    return build_mcp(Settings())


@pytest.fixture
def credentials():
    creds = WatchguardCredentials(
        access_id="placeholder-access-id", password="placeholder-password", api_key="placeholder-api-key"
    )
    token = set_credentials(creds)
    yield creds
    reset_credentials(token)


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    # Retry tests exercise real backoff/retry logic; skip the real sleeps.
    async def _noop(_seconds: float) -> None:
        return None

    monkeypatch.setattr(client_module, "_backoff_sleep", _noop)


async def test_tools_list_returns_full_catalog(mcp):
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOL_NAMES
    assert len(tools) == 17


async def test_get_account_success_returns_payload(mcp, credentials):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/audiences").mock(return_value=Response(200, json={"audience": "aud-1"}))
        mock.post("/oauth/token").mock(return_value=Response(200, json={"access_token": "opaque-token"}))
        mock.get("/v2/accounts/WGC-1-000000").mock(
            return_value=Response(200, json={"accountId": "WGC-1-000000", "name": "Acme MSP"})
        )
        async with Client(mcp) as client:
            result = await client.call_tool("watchguard_get_account", {"account_id": "WGC-1-000000"})
    payload = json.loads(result.data)
    assert "error" not in payload
    assert payload == {"accountId": "WGC-1-000000", "name": "Acme MSP"}


async def test_get_account_defaults_to_credential_owner_account(mcp, credentials):
    token = _fake_jwt({"account_id": "WGC-1-OWNER"})
    # assert_all_called=False: the whole point of this test is that
    # /v1/audiences must NOT be called when no explicit account id is given.
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        token_route = mock.post("/oauth/token").mock(return_value=Response(200, json={"access_token": token}))
        audience_route = mock.post("/v1/audiences").mock(return_value=Response(200, json={"audience": "should-not-be-called"}))
        owner_route = mock.get("/v2/accounts/WGC-1-OWNER").mock(
            return_value=Response(200, json={"accountId": "WGC-1-OWNER", "name": "Owner account"})
        )
        async with Client(mcp) as client:
            result = await client.call_tool("watchguard_get_account", {})
    payload = json.loads(result.data)
    assert payload == {"accountId": "WGC-1-OWNER", "name": "Owner account"}
    assert owner_route.call_count == 1
    assert token_route.call_count == 1
    # No explicit account id was given, so /v1/audiences (managed-account
    # delegation) must never be called, and no other account id is ever
    # substituted (AC2).
    assert audience_route.call_count == 0


async def test_managed_account_id_resolves_audience_before_token(mcp, credentials):
    with respx.mock(base_url=BASE_URL) as mock:
        audience_route = mock.post("/v1/audiences").mock(return_value=Response(200, json={"audience": "aud-xyz"}))
        token_route = mock.post("/oauth/token").mock(return_value=Response(200, json={"access_token": "scoped-token"}))
        mock.get("/v2/accounts/WGC-1-CHILD").mock(return_value=Response(200, json={"accountId": "WGC-1-CHILD"}))
        async with Client(mcp) as client:
            await client.call_tool("watchguard_get_account", {"account_id": "WGC-1-CHILD"})

        assert audience_route.call_count == 1
        assert token_route.call_count == 1
        token_request = token_route.calls[0].request
        body = token_request.read().decode()
        assert "audience=aud-xyz" in body
        # /v1/audiences must have been called before /oauth/token -- capture
        # call order before the router's call log is cleared on exit.
        call_paths = [c.request.url.path for c in mock.calls]
    assert call_paths.index("/v1/audiences") < call_paths.index("/oauth/token")


@pytest.mark.parametrize(
    "status,expected_code",
    [(404, "not_found"), (429, "rate_limited"), (500, "upstream_error")],
)
async def test_vendor_error_maps_to_structured_envelope(mcp, credentials, status, expected_code):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/audiences").mock(return_value=Response(200, json={"audience": "aud-1"}))
        mock.post("/oauth/token").mock(return_value=Response(200, json={"access_token": "opaque-token"}))
        account_route = mock.get("/v2/accounts/WGC-1-000000").mock(return_value=Response(status, json={"message": "boom"}))
        async with Client(mcp) as client:
            result = await client.call_tool("watchguard_get_account", {"account_id": "WGC-1-000000"})
    payload = json.loads(result.data)
    assert payload["error"]["code"] == expected_code
    if status in (429, 500):
        # Retried at least once before the final envelope was returned.
        assert account_route.call_count >= 2


def test_retry_delay_honors_retry_after_header():
    resp = Response(429, headers={"Retry-After": "7"})
    assert client_module.WatchguardClient._retry_delay(resp, attempt=1) == 7.0


async def test_delete_account_requires_account_id(mcp, credentials):
    async with Client(mcp) as client:
        result = await client.call_tool("watchguard_delete_account", {"account_id": ""})
    payload = json.loads(result.data)
    assert payload["error"]["code"] == "invalid_argument"


async def test_delete_operator_requires_identifiers(mcp, credentials):
    async with Client(mcp) as client:
        result = await client.call_tool("watchguard_delete_operator", {"username": ""})
    payload = json.loads(result.data)
    assert payload["error"]["code"] == "invalid_argument"


async def test_delete_tools_are_marked_destructive(mcp):
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert tools["watchguard_delete_account"].annotations.destructiveHint is True
    assert tools["watchguard_delete_operator"].annotations.destructiveHint is True


async def test_create_operator_returns_transaction_id(mcp, credentials):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/audiences").mock(return_value=Response(200, json={"audience": "aud-1"}))
        mock.post("/oauth/token").mock(return_value=Response(200, json={"access_token": "tok"}))
        mock.post("/v1/operators").mock(return_value=Response(200, json={"transaction_id": "txn-123"}))
        async with Client(mcp) as client:
            result = await client.call_tool(
                "watchguard_create_operator", {"username": "jdoe@example.com", "account_id": "WGC-1-000000"}
            )
    payload = json.loads(result.data)
    assert payload["transaction_id"] == "txn-123"


async def test_transaction_status_tool_returns_final_state(mcp, credentials):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/v1/audiences").mock(return_value=Response(200, json={"audience": "aud-1"}))
        mock.post("/oauth/token").mock(return_value=Response(200, json={"access_token": "tok"}))
        mock.get("/v1/TransactionStatus").mock(
            return_value=Response(200, json={"transaction_id": "txn-123", "status": "completed"})
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "watchguard_get_operator_transaction_status",
                {"transaction_id": "txn-123", "account_id": "WGC-1-000000"},
            )
    payload = json.loads(result.data)
    assert payload == {"transaction_id": "txn-123", "status": "completed"}
