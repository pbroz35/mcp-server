"""Placeholder capabilities — one of each kind, to copy from.

Delete these once you know what the server is actually for. They exist so the
server is testable end-to-end and so the shape of each capability is on hand:

  tool     — a function the model can call (does work, may have side effects)
  resource — read-only data the client can attach to context, addressed by URI
  prompt   — a reusable message template the user can invoke
"""

import logging
from datetime import UTC, datetime
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EchoResult(BaseModel):
    """Structured tool output. Returning a model (instead of a bare string)
    gives the client a JSON schema for the result."""

    message: str
    received_at: str = Field(description="UTC ISO-8601 timestamp of the call.")


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    async def echo(
        message: Annotated[str, Field(description="Text to echo back.")],
    ) -> EchoResult:
        """Echo a message back. Placeholder — replace with a real tool."""
        # The docstring above is sent to the model verbatim as the tool
        # description, so keep it about *when to use the tool* and put notes
        # like these in comments.
        #
        # A tool needing progress reporting, elicitation, or the incoming HTTP
        # headers takes an extra `ctx: Context` parameter (from
        # mcp.server.mcpserver); the SDK injects it and hides it from the
        # schema. Use plain `logging` — that is what reaches Cloud Logging.
        logger.info("echo called with %d chars", len(message))
        return EchoResult(
            message=message,
            received_at=datetime.now(UTC).isoformat(),
        )

    @mcp.resource("status://health")
    def health_resource() -> str:
        """Current server status, as a readable resource."""
        return f"ok — {datetime.now(UTC).isoformat()}"

    @mcp.prompt()
    def summarize(text: str) -> str:
        """Summarize a block of text."""
        return f"Summarize the following in three sentences:\n\n{text}"
