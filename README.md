# mcp-server

A general-purpose [MCP](https://modelcontextprotocol.io) server skeleton: one
placeholder tool, resource, and prompt, both transports wired up, and a
one-command deploy to Cloud Run. Nothing domain-specific yet — replace the
contents of `src/mcp_server/tools/` when you know what this is for.

Built on the Python SDK's `MCPServer` (`mcp` 2.x — the class was called
`FastMCP` in 1.x).

## Layout

```
src/mcp_server/
  __main__.py      CLI: stdio (default) or --http
  app.py           ASGI app for Cloud Run: /mcp + /health + auth middleware
  server.py        the MCPServer instance
  auth.py          shared-secret bearer check
  config.py        env-var settings
  tools/
    __init__.py    register_all() — the list of capability modules
    example.py     placeholder tool + resource + prompt
deploy.sh          Cloud Run deploy (creates the secret on first run)
```

## Local development

```bash
make install     # venv + editable install with dev extras
make test
make run         # stdio — what a local MCP client speaks
make serve       # HTTP on :8080
```

Copy `.env.example` to `.env` for local settings. With `MCP_AUTH_TOKEN` unset
the server accepts every request and logs a warning — fine on localhost, not
on a public URL.

Quick check against the HTTP transport:

```bash
curl -s -X POST http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

## Adding a capability

Create `src/mcp_server/tools/<area>.py` with a `register(mcp)` function, then
add it to `register_all()` in `tools/__init__.py`:

```python
def register(mcp: MCPServer) -> None:
    @mcp.tool()
    async def fetch_order(order_id: str) -> Order:
        """Look up an order by its ID."""   # <- the model reads this
        ...
```

Three things worth knowing:

- The docstring is the tool description sent to the model. Write it about when
  to use the tool, not how it works inside.
- Type annotations become the input schema; a Pydantic return type becomes the
  output schema. `Annotated[str, Field(description=...)]` documents a parameter.
- A tool that needs progress reporting, elicitation, or HTTP headers takes an
  extra `ctx: Context` parameter — the SDK injects it and keeps it out of the
  schema.

## Deploying to GCP

Cloud Run, because the server is a stateless HTTP service that should scale to
zero between calls. `stateless_http=True` means any instance can serve any
request, so no session affinity is needed.

```bash
brew install --cask google-cloud-sdk   # gcloud isn't installed on this machine yet
gcloud auth login
gcloud config set project <your-project>

PROJECT_ID=<your-project> ./deploy.sh
```

The script enables the APIs it needs, creates a `mcp-auth-token` secret with a
random 32-byte token on first run, grants the runtime service account access to
it, and deploys from source. It prints the service URL and the command to read
the token back.

### Why `--allow-unauthenticated`

Cloud Run IAM wants a Google-signed ID token on every request, which MCP
clients can't produce. So the service is publicly routable and
`auth.py` gates it on `Authorization: Bearer <MCP_AUTH_TOKEN>` instead,
compared in constant time. `/health` stays open for probes.

That is a shared secret, not real authorization: it can't tell two callers
apart or be revoked per client. If this ever handles anything sensitive,
move to the SDK's OAuth support (`MCPServer(auth=..., token_verifier=...)`)
and drop the middleware.

### Connecting a client

```bash
TOKEN=$(gcloud secrets versions access latest --secret=mcp-auth-token)
claude mcp add --transport http my-server https://<service-url>/mcp \
  --header "Authorization: Bearer $TOKEN"
```

### Cost

Scale-to-zero with `--min-instances=0`, so an idle server costs nothing beyond
the Artifact Registry image. The tradeoff is a cold start (a few seconds) on
the first call after idling; raise `--min-instances` if that gets annoying.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | *(empty)* | Shared secret; empty disables auth |
| `MCP_SERVER_NAME` | `mcp-server` | Name advertised to clients |
| `MCP_LOG_LEVEL` | `info` | `debug`/`info`/`warning`/`error` |
| `MCP_ALLOWED_HOSTS` | *(empty)* | Comma-separated Host allowlist; empty disables DNS-rebinding checks (correct behind Cloud Run) |
| `PORT` | `8080` | Set by Cloud Run |
