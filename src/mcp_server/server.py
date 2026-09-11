"""The MCPServer instance and its capability registration."""

import logging

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import settings
from .tools import register_all

logger = logging.getLogger(__name__)


def build_server() -> MCPServer:
    """Create the server and attach every tool/resource/prompt to it."""
    mcp = MCPServer(
        name=settings.server_name,
        version=__version__,
        instructions=(
            "A general-purpose MCP server. Capabilities live in "
            "mcp_server/tools/ — see that package for what is available."
        ),
        log_level=settings.log_level.upper(),
    )

    register_all(mcp)
    return mcp


mcp = build_server()
