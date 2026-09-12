"""Settings, read from environment variables (and .env locally)."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings are AGENT_-prefixed. PORT is the exception: Cloud Run sets it."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    openrouter_api_key: str = ""

    base_url: str = "https://openrouter.ai/api/v1"
    """OpenRouter speaks the OpenAI API, so any OpenAI-compatible gateway works
    here — point it at api.openai.com or a local vLLM to switch providers."""

    model: str = "qwen/qwen3.7-flash"
    """Must support tool calling, or the agent cannot call MCP tools at all.
    Cheap alternatives: deepseek/deepseek-v4-flash-0731, openai/gpt-oss-120b."""

    max_tokens: int = 8000
    temperature: float = 0.0
    """Deterministic tool selection matters more than variety in a research agent."""

    app_url: str = "http://localhost:3000"
    app_title: str = "Research Agent"
    """Sent to OpenRouter for attribution; it shows the app on their dashboard."""

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
        return bool(self.openrouter_api_key)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
