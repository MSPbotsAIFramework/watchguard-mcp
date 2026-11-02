"""Operator (admin user) management (WatchGuard Cloud Operator Management API v1).

Create/update/delete return a vendor transaction_id for the async operation;
poll it with watchguard_get_operator_transaction_status (AC7)."""

from __future__ import annotations

from typing import Any, Callable

from fastmcp import FastMCP

from ..client import WatchguardClient
from ._common import clamp_limit, require_account_id, require_arg, resolve_account, run_tool

ClientFactory = Callable[[], WatchguardClient]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool()
    async def watchguard_create_operator(
        username: str,
        account_id: str | None = None,
        role: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> str:
        """Create a WatchGuard operator (admin user) on an account. Async --
        returns a transaction_id; poll it with
        watchguard_get_operator_transaction_status.

        Args:
            username: Login/email for the new operator.
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            role: Optional operator role name.
            fields: Optional additional vendor fields not covered above.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                payload: dict[str, Any] = {
                    "accountId": require_account_id(resolved_id),
                    "username": require_arg(username, "username"),
                }
                if role:
                    payload["role"] = role
                if fields:
                    payload.update(fields)
                return await client.create_operator(token, payload)

        return await run_tool(body)

    @mcp.tool(annotations={"idempotentHint": True})
    async def watchguard_update_operator(username: str, account_id: str | None = None, fields: dict[str, Any] | None = None) -> str:
        """Update a WatchGuard operator. Async -- returns a transaction_id;
        poll it with watchguard_get_operator_transaction_status.

        Args:
            username: Operator to update (required; no "all operators" form).
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            fields: Vendor fields to change.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                payload: dict[str, Any] = {
                    "accountId": require_account_id(resolved_id),
                    "username": require_arg(username, "username"),
                }
                if fields:
                    payload.update(fields)
                return await client.update_operator(token, payload)

        return await run_tool(body)

    @mcp.tool(annotations={"destructiveHint": True})
    async def watchguard_delete_operator(username: str, account_id: str | None = None) -> str:
        """Delete a WatchGuard operator. Irreversible. Async -- returns a
        transaction_id; poll it with watchguard_get_operator_transaction_status.

        Args:
            username: Operator to delete (required; no "all operators" form).
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                payload = {
                    "accountId": require_account_id(resolved_id),
                    "username": require_arg(username, "username"),
                }
                return await client.delete_operator(token, payload)

        return await run_tool(body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_list_operators_by_account(account_id: str | None = None, limit: int = 50) -> str:
        """List operators (admin users) on an account.

        Args:
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            limit: Max results, default 50, hard cap 200.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                resolved_id, token = await resolve_account(client, account_id)
                return await client.list_operators_by_account(token, require_account_id(resolved_id), limit=clamp_limit(limit))

        return await run_tool(body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_get_operator_transaction_status(transaction_id: str, account_id: str | None = None) -> str:
        """Poll the outcome of an async operator create/update/delete call.

        Args:
            transaction_id: The transaction_id returned by a create/update/delete call.
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                _, token = await resolve_account(client, account_id)
                return await client.get_operator_transaction_status(token, require_arg(transaction_id, "transaction_id"))

        return await run_tool(body)
