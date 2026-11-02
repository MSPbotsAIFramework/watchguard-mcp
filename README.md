# watchguard-mcp

MCP server for [WatchGuard Cloud](https://www.watchguard.com/), exposing MSP account management, device/license activation, operator (admin user) management, and read-only allocation inventory as tools for the MSPbots Agent platform.

- Transport: MCP Streamable HTTP (`POST /mcp`), stateless.
- Stack: Python 3.12, FastMCP, httpx.
- License: Apache-2.0.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

Every request to `/mcp` must carry these headers (per-request, never persisted, never logged):

| Header | Required | Meaning | Where to obtain |
|---|---|---|---|
| `X-WatchGuard-Access-Id` | Yes | WatchGuard Cloud Access ID | WatchGuard Cloud → Manage Access page (per WatchGuard's API documentation) |
| `X-WatchGuard-Password` | Yes | Password paired with the Access ID for the OAuth client-credentials exchange | Same Manage Access page |
| `X-WatchGuard-Api-Key` | Yes | `WatchGuard-API-Key`, sent on every vendor call per WatchGuard's own API docs | Same Manage Access page |
| `X-WatchGuard-Account-Id` | No | Target managed (child) account id, format `WGC-1-xxxxxx`. Omit to act on the account owned by the credentials themselves | WatchGuard Cloud console, under the managed account's details |

Missing any required header returns HTTP 401 naming exactly which header is missing. There is no environment-variable fallback -- credentials only ever come from the request.

## What this connector covers (v1)

- **Accounts**: get, list children, create, update, delete a managed account.
- **Activations**: submit a device/license activation, list recent activations, check a submitted batch's status.
- **Operator management**: create, update, delete an operator (admin user), list operators, poll an async operator change's transaction status.
- **Allocations (read-only)**: allocation summary, allocations, licenses owned, assigned assets.

Allocation *mutation* (allocate/update/remove a device-license allocation) is explicitly out of scope for v1 -- it was not part of this ticket's requested capabilities and affects what a managed account is billed for. See `docs/tickets/PRD-21249.md` for the full design and the trade-offs behind each decision.

## Source layout

```
src/watchguard_mcp/
  settings.py     non-credential config (listen address, API base URL)
  context.py      request-scoped credential storage (ContextVar)
  middleware.py   reads credential headers, 401s on anything missing
  client.py       OAuth token exchange, audience resolution, retrying HTTP calls
  errors.py       structured error envelope
  server.py       FastMCP + Starlette wiring
  tools/          one module per resource domain
```

## Local development

```bash
uv sync
uv run pytest
uv run python -m watchguard_mcp   # starts on 0.0.0.0:8080
```

Build and run the container (must build for `linux/amd64`):

```bash
docker build --platform linux/amd64 -t watchguard-mcp:dev .
docker run --rm -p 8080:8080 watchguard-mcp:dev
```
