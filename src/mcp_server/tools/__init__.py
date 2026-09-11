"""Capability registration.

Add a module next to `web.py`, give it a `register(mcp)` function, and list it
here. Keeping registration explicit (rather than auto-importing) means an
import error surfaces at startup instead of silently dropping a tool.
"""

from mcp.server.mcpserver import MCPServer

from . import documents, web


def register_all(mcp: MCPServer) -> None:
    web.register(mcp)
    documents.register(mcp)
