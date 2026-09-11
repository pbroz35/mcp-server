"""Settings, read from environment variables (and .env locally)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings are AGENT_-prefixed. PORT is the exception: Cloud Run sets it."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    anthropic_api_key: str = ""

    model: str = "claude-opus-5"
    max_tokens: int = 16000
    effort: str = "high"
    """Thinking depth. 'low' for cheap runs, 'high' for real research."""

    mcp_url: str = "http://127.0.0.1:8080/mcp"
    """The deployed MCP server. Every tool the agent has comes from here."""

    mcp_token: str = ""
    """Bearer token for the MCP server, from its Secret Manager secret."""

    max_tool_iterations: int = 24
    """Hard stop, so a confused agent cannot loop on the corpus forever."""

    cors_origins: str = "http://localhost:3000"

    port: int = Field(default=8000, validation_alias="PORT")
    log_level: str = "info"

    @property
    def configured(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
