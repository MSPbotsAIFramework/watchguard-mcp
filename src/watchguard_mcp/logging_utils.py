"""Structured, per-request logging (SOP SS6, PRD-21249 review round 1 must-fix).

Every tool call (``run_tool``) and every outbound vendor request
(``WatchguardClient._send_raw``) logs one JSON line through this module,
correlated by a per-tool-call request id (see ``context.py``). Only
identifiers, tool names, API paths, status codes, timings, and the fixed
error-code vocabulary from ``errors.py`` are logged here -- callers must
never pass credentials, bearer tokens, or raw vendor response bodies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("watchguard_mcp")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    # Don't also hand these lines to the root logger -- we already emit a
    # complete JSON record ourselves, and double-propagation would duplicate
    # every line under uvicorn's own formatting.
    logger.propagate = False


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured (JSON) log line for ``event`` with ``fields``.

    Callers must not pass credentials, tokens, or raw vendor response bodies
    in ``fields`` -- only identifiers, paths, status codes, timings, and
    mapped error codes.
    """
    record = {"event": event, **fields}
    logger.info(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str))
