"""Device/license allocation inventory, read-only in v1 (WatchGuard Cloud
Allocations API v2). Mutating allocation endpoints are explicitly out of
scope for this version -- see tech design "Non-goals" / Decision 1."""

from __future__ import annotations

from typing import Any, Callable

from fastmcp import FastMCP

from ..client import WatchguardClient
from ._common import clamp_limit, require_account_id, require_arg, resolve_account, run_tool

ClientFactory = Callable[[], WatchguardClient]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_get_allocation_summary(resource_type: str, account_id: str | None = None) -> str:
        """Get the allocation summary for one resource type on an account.

        Args:
            resource_type: Vendor-defined resource type (e.g. a value from
                watchguard_list_allocations' own results).
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                return await client.get_allocation_summary(
                    token, require_account_id(resolved_id), require_arg(resource_type, "resource_type")
                )

        return await run_tool("watchguard_get_allocation_summary", body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_list_allocations(resource_type: str, account_id: str | None = None, limit: int = 50) -> str:
        """List current device/license allocations for one resource type.

        Args:
            resource_type: Vendor-defined resource type.
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            limit: Max results, default 50, hard cap 200.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                return await client.list_allocations(
                    token,
                    require_account_id(resolved_id),
                    require_arg(resource_type, "resource_type"),
                    limit=clamp_limit(limit),
                )

        return await run_tool("watchguard_list_allocations", body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_list_account_licenses(resource_type: str, account_id: str | None = None, limit: int = 50) -> str:
        """List licenses owned by an account for one resource type.

        Args:
            resource_type: Vendor-defined resource type.
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            limit: Max results, default 50, hard cap 200.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                return await client.list_account_licenses(
                    token,
                    require_account_id(resolved_id),
                    require_arg(resource_type, "resource_type"),
                    limit=clamp_limit(limit),
                )

        return await run_tool("watchguard_list_account_licenses", body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_list_assigned_assets(resource_type: str, account_id: str | None = None, limit: int = 50) -> str:
        """List assets currently assigned to devices for one resource type.

        Args:
            resource_type: Vendor-defined resource type.
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            limit: Max results, default 50, hard cap 200.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                return await client.list_assigned_assets(
                    token,
                    require_account_id(resolved_id),
                    require_arg(resource_type, "resource_type"),
                    limit=clamp_limit(limit),
                )

        return await run_tool("watchguard_list_assigned_assets", body)
