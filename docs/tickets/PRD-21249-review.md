# PRD-21249 · Code review

## Round 1 · 2026-11-02 · reviewed dev/PRD-21249 @ 2ea0897 (base main @ e8caef0)

Verdict: changes requested

### Scope

`git diff e8caef0...2ea0897` — the full first version of `MSPbotsAIFramework/watchguard-mcp` (greenfield repository, SOP "Main line A"). 24 files changed, all new.

### Verification performed

- `uv sync && uv run pytest`: 18 passed, 0 failed (independently re-run, matches the `[DEV]` stub's claim).
- CJK scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`): clean.
- `gitleaks detect --no-banner -s .`: `no leaks found` (4 commits scanned).
- README "MSPbots Connector" section vs `vendor-mcp-development/reference/readme-connector-section.md`: byte-identical (diffed programmatically, stripped-trailing-whitespace equal), and positioned before `## Authentication headers` per SOP §0.5.
- `sudo docker build --platform linux/amd64 -t watchguard-mcp:review-check .`: succeeds (all layers cached from the dev leg's own build, confirming reproducibility).
- Container smoke test: `GET /health` -> 200; `POST /mcp` with no credential headers -> 401; `docker exec whoami` -> `app` (non-root).
- Tool description lengths: all 17 tools checked programmatically — every description ≤500 chars and first line ≤100 chars (max observed: 413 chars total / 71 chars first line).
- `docs/tickets/PRD-21249.ac.json`: all 9 cases reviewed; TC1-TC8 pass with inline pytest evidence, TC9 is `blocked` with a stated reason (no real WatchGuard account available) that SOP/mcp-track.md explicitly exempts from gating INT publish.

### Findings

1. **[must-fix]** `src/watchguard_mcp/tools/_common.py:75` (`run_tool`) and `src/watchguard_mcp/client.py:168` (`_send_raw`) — **no structured logging exists anywhere in the codebase** (`grep -rn "logging\|logger\|log\." src/` returns nothing). SOP §6 requires structured (JSON/key=value) logs per request carrying a request-id, with tool name, outbound API path/status code, latency, and the mapped error `code` recorded (credentials, tokens, and raw vendor response bodies explicitly excluded) — and SOP §14's "日志与可观测性" checklist line is one of the criteria `mcp-track.md` §4.3 names as a must-fix gate for this review ("SOP §14 Checklist"). This is not a correctness bug — the tests and the self-test record are otherwise solid — but once this connector is live and handling real multi-tenant credential-bearing traffic, there is currently zero diagnostic trail for which tenant/tool/vendor-call combination failed, was rate-limited, or was slow: exactly the production-support gap §6 exists to prevent. `run_tool` (the single choke point every tool call already passes through) and `_send_raw` (the single choke point every outbound vendor call already passes through, which already has `method`/`path`/`attempt`/the response status in scope) are the natural, minimal insertion points — this does not require a redesign, just adding log calls at those two existing choke points.

### Suggestions

1. `src/watchguard_mcp/tools/_common.py:29` (`to_json`) — list tools return the vendor's response payload verbatim rather than trimming to the fields the tool's own docstring advertises (SOP §2 "返回已裁剪字段", an "应当"/should-level item per SOP §0.1, not blocking). Not changing this now is reasonable given the tech design's own acknowledgment that the exact vendor response shape is unconfirmed without a live account (Open questions / Risks & dependencies) — trimming fields you haven't verified exist risks silently dropping data a caller needs. Worth revisiting once TC9 is validated against a real account.

### Fixes (dev01, rework round 1)

1. **[must-fix] Structured logging added at the two named choke points** (`tools/_common.py:run_tool`, `client.py:_send_raw`). Fixed in the commit(s) immediately following this entry on `dev/PRD-21249`; the final pushed sha is in the `[DEV]` stub's `MCP:` line:
   - New `src/watchguard_mcp/logging_utils.py`: `log_event(event, **fields)` — one JSON line per call via a module-level `watchguard_mcp` logger (level INFO, its own `StreamHandler` to stdout, `propagate=False` so lines aren't duplicated under uvicorn's own formatting).
   - `context.py`: added a `request_id` `ContextVar` (`new_request_id` / `set_request_id` / `reset_request_id` / `get_request_id`), mirroring the existing credentials `ContextVar`. `get_request_id()` returns `"unscoped"` instead of raising when called outside a tool call (e.g. a test that drives `WatchguardClient` directly), since a missing request id is a log-correlation gap, not a tenant-isolation bug — unlike `get_credentials()`.
   - `tools/_common.py`: `run_tool` now takes `tool_name: str` as its first argument. Generates one request id per call, publishes it via `context.set_request_id` for the duration of the call, and logs one `tool_call` event: `request_id`, `tool`, `status` (`ok`/`error`), `latency_ms`, and `error_code` (the mapped `WatchguardError.code`) on failure. Never logs the result payload or the raw exception. All 17 call sites across `tools/accounts.py` (5), `tools/activations.py` (3), `tools/allocations.py` (4), `tools/operators.py` (5) updated mechanically to pass their own tool name — verified each matches `test_tools.py`'s `EXPECTED_TOOL_NAMES` set.
   - `client.py`: `_send_raw` reads the request id via `context.get_request_id()` and logs one `vendor_call` event per HTTP attempt: `request_id`, `method`, `path`, `attempt`, and either `status_code` (got a response) or `status: timeout|network_error` (transport failure), plus `latency_ms`. Request/response headers (bearer token, `WatchGuard-API-Key`) and bodies are never passed to `log_event`.
   - **Scope decision**: SOP §6 also lists "入参摘要（脱敏）" (sanitized arg summary) as a thing to log; this fix does not add one. The review finding's own restatement of what's required (request-id, tool name, API path/status, latency, error code) does not include it, and account ids / usernames passed as tool args are themselves tenant-identifying, so omitting a generic arg dump avoids re-introducing a smaller version of the same leakage risk §6 warns against. If a specific arg needs to be traceable, that's a follow-up, not implied by this must-fix.
   - **Verified end-to-end** (not just unit tests): `scratch/PRD-21249/log_smoke.py` (kept in the pipeline skill's scratch dir, not this repo) drives a real `tools/call` through `fastmcp.Client` against a mocked WatchGuard API (success path and a 404 error path). Captured log lines show a single `request_id` shared across the `vendor_call` lines (`/v1/audiences`, `/oauth/token`, `/v2/accounts/...`) and the closing `tool_call` line, with `tool`, `status`, `latency_ms`, and (on the error path) `error_code: not_found` all present, and no header/credential values anywhere in the output.
   - **Full gate re-run on the fixed code** (same commands as round 1's self-test): `uv sync && uv run pytest` → 18 passed, 0 failed (unchanged — this fix adds no new behavior to any tool's input/output contract, so no existing test needed to change and none of TC1–TC8 required re-execution beyond this same pytest run). CJK scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`): clean in `src/` and in the new/changed files; the scan also still matches the two quoted Chinese SOP section titles inside *this file's own Round 1 text above* (lines pre-dating this fix, written by the reviewer, not touched here — out of scope for this must-fix). `gitleaks detect --no-banner -s .`: `no leaks found` (5 commits scanned). README "MSPbots Connector" section vs `vendor-mcp-development/reference/readme-connector-section.md`: byte-identical (unchanged by this fix). `docker build --platform linux/amd64`: succeeds. Container smoke test: `GET /health` → 200, `POST /mcp` with no credential headers → 401, `docker exec whoami` → `app` (non-root) — all unchanged from round 1.

## Round 2 · 2026-11-02 · reviewed dev/PRD-21249 @ efc944b (base main @ e8caef0)

Verdict: approved

### Scope

`git diff 2ea0897...efc944b` — the round 1 fix only: new `src/watchguard_mcp/logging_utils.py`; `context.py` gains a `request_id` `ContextVar`; `client.py` `_send_raw` and `tools/_common.py` `run_tool` emit the two log events; all 17 `run_tool(...)` call sites across `tools/{accounts,activations,allocations,operators}.py` updated to the new `run_tool(tool_name, body)` signature. No change to `tests/`, `docs/tickets/PRD-21249.ac.json`, or the frozen `docs/tickets/PRD-21249.md` — correct, since this is a pure logging/observability fix that doesn't touch any AC-facing behavior or tool contract.

### Verification performed (independently re-run, not just re-reading the Fixes note)

- `uv sync && uv run pytest -q`: 18 passed, 0 failed.
- CJK scan: clean in `src/`; the only hits anywhere in the tree are the quoted Chinese SOP section titles inside this review file's own Round 1 prose above (pre-existing, not code).
- `grep -rn "run_tool(" src/` minus the `def`: all 17 call sites pass a `tool_name` string as the first argument; none left on the old one-arg signature.
- `src/watchguard_mcp/errors.py`: confirmed `WatchguardError.code` is a real attribute, so `exc.code` used in the new `tool_call` error log is correct.
- README "MSPbots Connector" section vs `vendor-mcp-development/reference/readme-connector-section.md`: byte-identical (diffed programmatically).
- `docker build --platform linux/amd64 -t watchguard-mcp:review-r2 .`: succeeds.
- **Live container smoke test, run myself end-to-end** (not the dev's `scratch/` script): started the built image; `GET /health` → 200; `POST /mcp` with no credential headers → 401; `docker exec whoami` → `app`; then called `initialize` and `tools/call watchguard_get_account` with placeholder credential headers (no real vendor account, so the outbound call 400s against the real WatchGuard OAuth endpoint — expected). `docker logs` showed exactly the two claimed structured JSON lines:
  ```
  {"event":"vendor_call","request_id":"005b60e0a2cd","method":"POST","path":"/oauth/token","attempt":1,"status_code":400,"latency_ms":418.8}
  {"event":"tool_call","request_id":"005b60e0a2cd","tool":"watchguard_get_account","status":"error","error_code":"invalid_argument","latency_ms":529.2}
  ```
  Same `request_id` on both lines, no credential/token values anywhere in the output. This independently confirms the round 1 must-fix is genuinely fixed, not just claimed.

### Findings

None. Round 1's must-fix is resolved; no new must-fix found in this round's diff.

### Suggestions carried over (unchanged, still not blocking)

1. `src/watchguard_mcp/tools/_common.py:29` (`to_json`) — list tools still return the vendor's response payload verbatim rather than trimming to documented fields (SOP §2, should-level). Unchanged by this fix; same rationale as round 1 (exact vendor response shape unconfirmed without a live account). Worth revisiting once TC9 is validated.

Status: frozen @ efc944b
