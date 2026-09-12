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
    """Shared secret sent as `Authorization: Bearer <token>`. Empty disables
    auth, which is safe only for local stdio use."""

    port: int = Field(default=8080, validation_alias="PORT")

    log_level: str = "info"

    allowed_hosts: str = ""
    """Comma-separated Host allowlist for DNS-rebinding protection. Empty
    disables the check, which is correct behind Cloud Run."""

    # --- Retrieval stack -------------------------------------------------

    database_url: str = ""
    """Neon connection string; empty disables the document tools. Use the
    pooled endpoint, or Cloud Run cold starts will exhaust connections."""

    openai_api_key: str = ""
    """Key for embeddings only — this server never calls a chat model."""

    openai_base_url: str = ""
    """Override the embeddings endpoint. Empty means OpenAI directly; set it to
    another OpenAI-compatible gateway to use one key for everything."""

    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    """Must match the vector(N) column. Changing it without re-embedding the
    corpus silently corrupts every search."""

    tavily_api_key: str = ""
    """Key for web search. Empty disables the web_search tool."""

    chunk_tokens: int = 512
    """Big enough to carry an argument, small enough that a hit is specific."""

    chunk_overlap_tokens: int = 64
    """Overlap so a fact spanning a boundary survives in one whole chunk."""

    max_upload_bytes: int = 25 * 1024 * 1024

    @property
    def documents_enabled(self) -> bool:
        return bool(self.database_url and self.openai_api_key)

    @property
    def web_search_enabled(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def bearer_token(self) -> str:
        """The token without surrounding whitespace. Secret payloads often end
        in a newline that clients strip on read, so comparing raw rejects them."""
        return self.auth_token.strip()

    @property
    def auth_enabled(self) -> bool:
        return bool(self.bearer_token)

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


settings = Settings()
