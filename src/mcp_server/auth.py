"""Shared-secret bearer auth for the HTTP transport.

Cloud Run runs --allow-unauthenticated because MCP clients cannot mint Google
ID tokens, so this middleware is what actually gates access.
"""

import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str, exempt_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self.token = token
        self.exempt_paths = exempt_paths or set()

    async def dispatch(self, request: Request, call_next):
        if not self.token or request.url.path in self.exempt_paths:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")

        if scheme.lower() != "bearer" or not hmac.compare_digest(presented, self.token):
            logger.warning("rejected unauthenticated request to %s", request.url.path)
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
