"""Runtime configuration, read from environment variables (and .env locally)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings are MCP_-prefixed (MCP_AUTH_TOKEN, MCP_LOG_LEVEL, ...).

    PORT is the exception: Cloud Run injects it unprefixed.
    """

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server_name: str = "mcp-server"
    """Name advertised to MCP clients during initialization."""

    auth_token: str = ""
    """Shared secret clients send as `Authorization: Bearer <token>`.

    Empty disables auth. Keep it empty only for local/stdio use — an
    unauthenticated public service exposes every tool to the internet.
    """

    port: int = Field(default=8080, validation_alias="PORT")

    log_level: str = "info"

    allowed_hosts: str = ""
    """Comma-separated Host header allowlist for DNS-rebinding protection.

    Empty turns the check off, which is what you want behind Cloud Run: the
    load balancer terminates TLS and the Host is your *.run.app (or custom)
    domain, so pinning it here just breaks deploys. Set it if you serve the
    app directly to browsers from a known origin.
    """

    @property
    def bearer_token(self) -> str:
        """The token, minus surrounding whitespace.

        Secret payloads very often end in a newline (anything piped from
        `openssl rand` does), and clients read them back with `$(...)`, which
        strips it. Comparing raw would reject every legitimate caller.
        """
        return self.auth_token.strip()

    @property
    def auth_enabled(self) -> bool:
        return bool(self.bearer_token)

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


settings = Settings()
