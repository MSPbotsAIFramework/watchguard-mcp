"""Missing-header 401 behavior and request-level credential isolation
(TC3, TC8). Exercises CredentialsMiddleware directly against a minimal
Starlette app -- no MCP protocol machinery needed for this layer."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from watchguard_mcp.context import get_credentials
from watchguard_mcp.middleware import CredentialsMiddleware

ALL_HEADERS = {
    "X-WatchGuard-Access-Id": "the-access-id",
    "X-WatchGuard-Password": "the-password",
    "X-WatchGuard-Api-Key": "the-api-key",
}


async def _echo_credentials(request):
    creds = get_credentials()
    return JSONResponse({"access_id": creds.access_id, "account_id": creds.account_id})


def _build_app() -> Starlette:
    app = Starlette(routes=[Route("/mcp", _echo_credentials, methods=["POST"])])
    app.add_middleware(CredentialsMiddleware)
    return app


async def _post(headers: dict[str, str]) -> httpx.Response:
    transport = ASGITransport(app=_build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/mcp", headers=headers)


async def test_missing_access_id_returns_401_naming_header():
    headers = dict(ALL_HEADERS)
    del headers["X-WatchGuard-Access-Id"]
    resp = await _post(headers)
    assert resp.status_code == 401
    assert resp.json()["missing_headers"] == ["X-WatchGuard-Access-Id"]


async def test_missing_password_returns_401_naming_header():
    headers = dict(ALL_HEADERS)
    del headers["X-WatchGuard-Password"]
    resp = await _post(headers)
    assert resp.status_code == 401
    assert resp.json()["missing_headers"] == ["X-WatchGuard-Password"]


async def test_missing_api_key_returns_401_naming_header():
    headers = dict(ALL_HEADERS)
    del headers["X-WatchGuard-Api-Key"]
    resp = await _post(headers)
    assert resp.status_code == 401
    assert resp.json()["missing_headers"] == ["X-WatchGuard-Api-Key"]


async def test_all_headers_present_returns_200_with_credentials_in_context():
    resp = await _post({**ALL_HEADERS, "X-WatchGuard-Account-Id": "WGC-1-000000"})
    assert resp.status_code == 200
    assert resp.json() == {"access_id": "the-access-id", "account_id": "WGC-1-000000"}


async def test_concurrent_requests_do_not_share_context_var():
    transport = ASGITransport(app=_build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def call(tag: str) -> dict:
            headers = {**ALL_HEADERS, "X-WatchGuard-Access-Id": f"access-{tag}", "X-WatchGuard-Account-Id": f"account-{tag}"}
            resp = await client.post("/mcp", headers=headers)
            return resp.json()

        results = await asyncio.gather(*(call(tag) for tag in ("a", "b", "c", "d")))

    by_access = {r["access_id"]: r["account_id"] for r in results}
    assert by_access == {
        "access-a": "account-a",
        "access-b": "account-b",
        "access-c": "account-c",
        "access-d": "account-d",
    }
