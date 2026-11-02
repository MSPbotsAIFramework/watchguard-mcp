"""Entry point: start the Streamable HTTP server."""

from __future__ import annotations

import uvicorn

from .server import build_app
from .settings import get_settings


def main() -> None:
    settings = get_settings()
    app = build_app(settings)
    uvicorn.run(app, host=settings.mcp_http_host, port=settings.mcp_http_port, log_level="info")


if __name__ == "__main__":
    main()
