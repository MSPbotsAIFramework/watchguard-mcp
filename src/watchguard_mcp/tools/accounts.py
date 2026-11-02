"""Accounts (WatchGuard Cloud Accounts API v2)."""

from __future__ import annotations

from typing import Any, Callable

from fastmcp import FastMCP

from ..client import WatchguardClient
from ._common import clamp_limit, require_account_id, require_arg, resolve_account, run_tool

ClientFactory = Callable[[], WatchguardClient]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_get_account(account_id: str | None = None) -> str:
        """Get a WatchGuard Cloud account.

        Args:
            account_id: Target account id (format WGC-1-xxxxxx). Omit to use
                the account owned by the caller's own credentials.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                return await client.get_account(token, require_account_id(resolved_id))

        return await run_tool("watchguard_get_account", body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_list_child_accounts(
        account_id: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> str:
        """List the managed (child) accounts under a parent account.

        Args:
            account_id: Parent account id. Omit to use the account owned by
                the caller's own credentials.
            limit: Max results, default 50, hard cap 200.
            cursor: Opaque pagination cursor from a previous call's has_more result.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                return await client.list_child_accounts(
                    token, require_account_id(resolved_id), limit=clamp_limit(limit), cursor=cursor
                )

        return await run_tool("watchguard_list_child_accounts", body)

    @mcp.tool()
    async def watchguard_create_account(
        name: str,
        parent_account_id: str | None = None,
        locale: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> str:
        """Create a new managed (child) account under a parent account.

        Args:
            name: Display name for the new account.
            parent_account_id: Parent account id. Omit to use the account
                owned by the caller's own credentials.
            locale: Optional locale, e.g. "en-US".
            fields: Optional additional vendor fields not covered above.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, parent_account_id)
                payload: dict[str, Any] = {"name": require_arg(name, "name")}
                if locale:
                    payload["locale"] = locale
                if fields:
                    payload.update(fields)
                return await client.create_account(token, require_account_id(resolved_id), payload)

        return await run_tool("watchguard_create_account", body)

    @mcp.tool(annotations={"idempotentHint": True})
    async def watchguard_update_account(account_id: str, fields: dict[str, Any]) -> str:
        """Update a WatchGuard Cloud account's fields.

        Args:
            account_id: Account id to update (required; no "all accounts" form).
            fields: Vendor fields to change, e.g. {"name": "New Name"}.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                _, token = await resolve_account(client, account_id)
                return await client.update_account(token, require_arg(account_id, "account_id"), fields)

        return await run_tool("watchguard_update_account", body)

    @mcp.tool(annotations={"destructiveHint": True})
    async def watchguard_delete_account(account_id: str) -> str:
        """Delete a WatchGuard Cloud managed account. Irreversible.

        Args:
            account_id: Account id to delete (required; no "all accounts" form).
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                _, token = await resolve_account(client, account_id)
                return await client.delete_account(token, require_arg(account_id, "account_id"))

        return await run_tool("watchguard_delete_account", body)
