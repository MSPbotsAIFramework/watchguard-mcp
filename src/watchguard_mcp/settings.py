"""Non-credential runtime configuration.

Credentials are never configured here -- they arrive per request as HTTP
headers (see context.py / middleware.py). This module only knows about the
listen address and the vendor API's base URL.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    # Overridable for tests only; not exposed to callers and not read from
    # any per-tenant credential source.
    watchguard_api_base_url: str = "https://api.usa.cloud.watchguard.com"


def get_settings() -> Settings:
    return Settings()
