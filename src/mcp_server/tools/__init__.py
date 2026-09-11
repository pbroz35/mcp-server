"""Capability registration: add a module next to `web.py` with a `register(mcp)`
function and list it here. Explicit beats auto-import, which drops tools silently.
"""

from mcp.server.mcpserver import MCPServer

from . import documents, web


def register_all(mcp: MCPServer) -> None:
    web.register(mcp)
    documents.register(mcp)
