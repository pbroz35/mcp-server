"""ASGI entrypoint for the streamable HTTP transport.

    uvicorn mcp_server.app:app --host 0.0.0.0 --port 8080

MCP clients use /mcp, uploads POST to /documents, and /health is open for probes.
"""

import logging

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import BearerTokenMiddleware
from .config import settings
from .server import mcp
from .uploads import upload_document

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# NOT /healthz: Google Frontend intercepts that exact path on *.run.app.
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "server": settings.server_name,
            # Surface live capabilities, so a misconfigured deploy shows up in
            # the probe rather than in a failing tool call.
            "documents": settings.documents_enabled,
            "web_search": settings.web_search_enabled,
        }
    )


# Registered on the same Starlette app as /mcp, so uploads sit behind the same
# bearer-token middleware.
mcp.custom_route("/documents", methods=["POST"])(upload_document)


def create_app():
    # Extend the SDK's app rather than wrapping it: it carries the session
    # manager's lifespan, which never runs if mounted inside a new app.
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        # Lets Cloud Run scale without sticky sessions.
        stateless_http=True,
        # Only selects DNS-rebinding defaults; uvicorn does the binding.
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
