"""Device/license activations (WatchGuard Cloud Activations API v1)."""

from __future__ import annotations

from typing import Any, Callable

from fastmcp import FastMCP

from ..client import WatchguardClient
from ._common import clamp_limit, require_arg, resolve_account, run_tool

ClientFactory = Callable[[], WatchguardClient]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool()
    async def watchguard_activate_device(
        license_key: str,
        account_id: str | None = None,
        device_tag: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> str:
        """Submit a device/license activation request. Not idempotent --
        resubmitting creates a duplicate activation.

        Args:
            license_key: The license or activation key to activate.
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            device_tag: Optional caller-assigned label for the device.
            fields: Optional additional vendor fields not covered above.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                _, token = await resolve_account(client, account_id)
                payload: dict[str, Any] = {"licenseKey": require_arg(license_key, "license_key")}
                if device_tag:
                    payload["deviceTag"] = device_tag
                if fields:
                    payload.update(fields)
                return await client.activate_device(token, payload)

        return await run_tool(body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_list_recent_activations(account_id: str | None = None, limit: int = 50) -> str:
        """List activations submitted in the last 30 days.

        Args:
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
            limit: Max results, default 50, hard cap 200.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                _, token = await resolve_account(client, account_id)
                return await client.list_recent_activations(token, limit=clamp_limit(limit))

        return await run_tool(body)

    @mcp.tool(annotations={"readOnlyHint": True})
    async def watchguard_get_activation_batch_status(batch_id: str, account_id: str | None = None) -> str:
        """Check the processing status of a previously submitted activation batch.

        Args:
            batch_id: The batch id returned by watchguard_activate_device.
            account_id: Target account id. Omit to use the account owned by
                the caller's own credentials.
        """

        async def body() -> dict[str, Any]:
            async with client_factory() as client:
                _, token = await resolve_account(client, account_id)
                return await client.get_activation_batch_status(token, require_arg(batch_id, "batch_id"))

        return await run_tool(body)
