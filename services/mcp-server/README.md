# mcp-server

The tool layer for a research agent, exposed over
[MCP](https://modelcontextprotocol.io): live web search, and semantic search
over a corpus of documents you upload. Deploys to Cloud Run with one command.

An agent connected to this server implements no integrations of its own —
every capability arrives over MCP, so the tool layer can change without
touching the agent.

| Tool | What it does |
| --- | --- |
| `web_search` | Live web search via Tavily, returning extracted passages, not just links |
| `search_documents` | Hybrid semantic + keyword search over uploaded documents, filterable by metadata |
| `get_context` | Expands a search hit with the surrounding text, for fair quotation |
| `list_documents` | What is in the corpus, and which metadata keys exist to filter on |

Documents are uploaded over HTTP (`POST /documents`), not through a tool — a
PDF has no business passing through the model's context on its way into a
database.

Built on the Python SDK's `MCPServer` (`mcp` 2.x — the class was called
`FastMCP` in 1.x).

## Layout

```
src/mcp_server/
  __main__.py      CLI: stdio (default), --http, or --init-db
  app.py           ASGI app: /mcp + /documents + /health + auth middleware
  server.py        the MCPServer instance
  auth.py          shared-secret bearer check
  config.py        env-var settings
  db.py            pgvector schema, connection pool, hybrid search SQL
  ingest.py        PDF extraction, cleaning, chunking, embedding
  uploads.py       POST /documents
  tools/
    __init__.py    register_all() — the list of capability modules
    web.py         web_search
    documents.py   search_documents, get_context, list_documents
deploy.sh          Cloud Run deploy (creates the secret on first run)
```

## How retrieval works

Uploading a PDF extracts text per page, de-hyphenates and unwraps it, splits it
into ~512-token chunks on paragraph boundaries, embeds each chunk, and stores
them in Postgres with `pgvector`.

Search runs two queries and fuses them:

```
query ──┬─► embed ──► vector similarity (HNSW, cosine)  ──┐
        │                                                 ├─► Reciprocal Rank Fusion ──► top k
        └─► websearch_to_tsquery ──► keyword rank (GIN) ──┘
```

Two arms because each fails differently: vector search misses exact tokens (a
ticker, a case number, a name the embedding smooths away), and keyword search
misses paraphrase. RRF combines them by rank alone, so the two incomparable
score scales never need normalizing.

Metadata filtering happens *before* ranking, via JSONB containment. Upload a
filing tagged `{"company": "NVDA", "form": "10-K", "year": 2025}` and later
search only within it — no schema migration to add a new key.

## Uploading documents

```bash
curl -X POST https://<service-url>/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@nvidia-10k.pdf" \
  -F "title=NVIDIA FY2025 10-K" \
  -F "source=https://www.sec.gov/..." \
  -F 'metadata={"company":"NVDA","form":"10-K","year":2025}'
```

Returns the document id and chunk count. Re-uploading identical bytes replaces
the existing document's chunks rather than duplicating them — the hash of the
file is the identity, so the corpus cannot silently accumulate the same PDF
three times under three titles.

Supported: PDF, plain text, Markdown. Scanned PDFs with no text layer are
rejected with a clear error; this server does not do OCR.

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

The database and API keys are **not** wired into the deploy script yet — add
them as secrets and pass them with `--set-secrets` when you deploy, or the
deployed instance runs with document search and web search disabled. `GET
/health` reports which capabilities are actually live.

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

## Setup

Two external services, both with usable free tiers:

1. **[Neon](https://neon.tech)** — Postgres with `pgvector`. Create a project,
   then copy the **pooled** connection string (the host contains `-pooler`).
   Neon scales to zero like Cloud Run, so an idle corpus costs nothing.
2. **[OpenAI](https://platform.openai.com)** — embeddings only; this server
   never calls a chat model. `text-embedding-3-small` is about $0.02 per
   million tokens, so a few hundred PDFs cost cents.
3. **[Tavily](https://tavily.com)** — web search. Optional; without a key the
   `web_search` tool reports itself unavailable and the rest still works.

Then create the schema:

```bash
make install
cp .env.example .env   # fill in the three keys
.venv/bin/python -m mcp_server --init-db
```

`--init-db` is idempotent, so it is safe on every deploy.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | *(empty)* | Shared secret; empty disables auth |
| `MCP_DATABASE_URL` | *(empty)* | Neon pooled connection string; empty disables document tools |
| `MCP_OPENAI_API_KEY` | *(empty)* | Embeddings only |
| `MCP_TAVILY_API_KEY` | *(empty)* | Web search; empty disables `web_search` |
| `MCP_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `MCP_EMBEDDING_DIMENSIONS` | `1536` | Must match the `vector(N)` column |
| `MCP_CHUNK_TOKENS` | `512` | Target chunk size |
| `MCP_CHUNK_OVERLAP_TOKENS` | `64` | Overlap between chunks |
| `MCP_MAX_UPLOAD_BYTES` | `26214400` | Upload size cap (25 MB) |
| `MCP_SERVER_NAME` | `mcp-server` | Name advertised to clients |
| `MCP_LOG_LEVEL` | `info` | `debug`/`info`/`warning`/`error` |
| `MCP_ALLOWED_HOSTS` | *(empty)* | Comma-separated Host allowlist; empty disables DNS-rebinding checks (correct behind Cloud Run) |
| `PORT` | `8080` | Set by Cloud Run |
