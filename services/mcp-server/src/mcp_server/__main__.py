"""CLI entrypoint.

    python -m mcp_server           # stdio — for local clients (Claude Code, Desktop)
    python -m mcp_server --http    # streamable HTTP — what Cloud Run runs
    python -m mcp_server --init-db # apply the pgvector schema, then exit
"""

import argparse
import logging
import sys

from .config import settings


def main() -> int:
    parser = argparse.ArgumentParser(prog="mcp-server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve over streamable HTTP instead of stdio.",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Create the pgvector extension, tables and indexes, then exit. Idempotent.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    if args.init_db:
        import asyncio

        logging.basicConfig(level=settings.log_level.upper(), stream=sys.stderr)
        from .db import close_pool, init_schema

        async def run() -> None:
            try:
                await init_schema()
            finally:
                await close_pool()

        asyncio.run(run())
        print("Schema applied.")
        return 0

    if args.http:
        import uvicorn

        uvicorn.run(
            "mcp_server.app:app",
            host=args.host,
            port=args.port,
            log_level=settings.log_level,
        )
        return 0

    # stdio: logs go to stderr, because stdout is the MCP wire protocol.
    logging.basicConfig(
        level=settings.log_level.upper(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from .server import mcp

    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
