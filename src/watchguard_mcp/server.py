"""FastMCP server factory and the Starlette app that serves it.

Built by hand (rather than FastMCP's `http_app()` convenience wrapper) so we
can pass `TransportSecuritySettings(enable_dns_rebinding_protection=False)`
into the Streamable HTTP session manager -- required because the service
sits behind an internal reverse proxy, not localhost (SOP SS7).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .client import WatchguardClient
from .context import get_credentials
from .middleware import CredentialsMiddleware
from .settings import Settings
from .tools import accounts, activations, allocations, operators

SERVICE_INSTRUCTIONS = (
    "WatchGuard Cloud MSP management: manage MSP and managed (child) accounts, "
    "activate devices/licenses, administer operator (admin user) access, and "
    "read device/license allocation inventory. Typical flow: call "
    "watchguard_get_account or watchguard_list_child_accounts to find the "
    "target account, then act on it -- activation, operator, and allocation "
    "tools all take that account's id. Omit account id to act on the account "
    "owned by the caller's own credentials; set an explicit account id (or "
    "the X-WatchGuard-Account-Id header) to act on a managed customer "
    "account the caller has been delegated access to."
)

MCP_PATH = "/mcp"


def build_mcp(settings: Settings) -> FastMCP:
    # Statelessness is enforced below on the StreamableHTTPSessionManager
    # (`stateless=True`) since this app is built by hand rather than through
    # FastMCP's `http_app()`/`run()`, where `stateless_http=` here would
    # otherwise apply (and is deprecated on the constructor as of fastmcp 2.14).
    mcp = FastMCP(name="watchguard-mcp", instructions=SERVICE_INSTRUCTIONS)

    def client_factory() -> WatchguardClient:
        return WatchguardClient(get_credentials(), settings.watchguard_api_base_url)

    accounts.register(mcp, client_factory)
    activations.register(mcp, client_factory)
    allocations.register(mcp, client_factory)
    operators.register(mcp, client_factory)
    return mcp


class _McpAsgiApp:
    """Thin ASGI wrapper so Starlette's Route treats this as a raw ASGI app
    (matched against MCP_PATH exactly) rather than a request/response
    endpoint -- see Starlette's Route.__init__ function-vs-class check."""

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self._session_manager.handle_request(scope, receive, send)


async def health(_: Request) -> JSONResponse:
    # Pure local probe -- must never depend on the vendor API (SOP SS1.1).
    return JSONResponse({"status": "ok"})


def build_app(settings: Settings | None = None) -> Starlette:
    settings = settings or Settings()
    mcp = build_mcp(settings)

    session_manager = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    mcp_app = _McpAsgiApp(session_manager)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncGenerator[None, None]:
        # Mount()/Route() do not run a sub-app's own lifespan, so the
        # session manager's run() (and FastMCP's own lifespan manager) must
        # be wired into the *outer* app's lifespan explicitly (SOP SS7).
        async with mcp._lifespan_manager(), session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route(MCP_PATH, endpoint=mcp_app),
        ],
        lifespan=lifespan,
    )
    app.add_middleware(CredentialsMiddleware)
    return app
