"""ASGI entrypoint for the streamable HTTP transport.

    uvicorn mcp_server.app:app --host 0.0.0.0 --port 8080

MCP clients connect to /mcp. /health is unauthenticated, for Cloud Run probes.
"""

import logging

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import BearerTokenMiddleware
from .config import settings
from .server import mcp

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# NOT /healthz: Google Frontend intercepts that exact path on *.run.app and
# returns its own 404 without ever reaching the container.
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": settings.server_name})


def create_app():
    # The SDK builds the Starlette app, including the session-manager lifespan
    # the streamable transport needs — extend that app, don't wrap it in a new
    # one, or the lifespan never runs.
    #
    # stateless_http=True: every request is self-contained, so Cloud Run can
    # scale to N instances without sticky sessions. Set it False only if you
    # add state that must survive between requests on one connection.
    #
    # host is passed through only to decide DNS-rebinding defaults; uvicorn
    # does the actual binding.
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(settings.allowed_hosts_list),
            allowed_hosts=settings.allowed_hosts_list,
        ),
    )
    app.add_middleware(
        BearerTokenMiddleware,
        token=settings.bearer_token,
        exempt_paths={"/health"},
    )

    if not settings.auth_enabled:
        logger.warning(
            "MCP_AUTH_TOKEN is unset — every request is accepted. "
            "Do not run like this on a public URL."
        )

    return app


app = create_app()
