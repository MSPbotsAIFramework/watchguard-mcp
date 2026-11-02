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
