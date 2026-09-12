# research-agent

A research agent in three independently deployable services. The agent plans and
reasons; every capability it has arrives over MCP; the UI shows the tool calls as
they happen.

```
  ┌────────────────┐   AG-UI events (SSE)   ┌──────────────────┐
  │   frontend     │ ◄───────────────────── │     backend      │
  │  Next.js 16    │                        │ LangChain deep   │
  │  @ag-ui/client │ ──────────────────────►│ agent (LangGraph)│
  └────────────────┘   RunAgentInput        └────────┬─────────┘
                                                     │ MCP (streamable HTTP)
                                                     ▼
                                            ┌──────────────────┐
                                            │   mcp-server     │
                                            │  deployed on     │
                                            │  Cloud Run       │
                                            └────────┬─────────┘
                                                     │
                                      ┌──────────────┴──────────────┐
                                      ▼                             ▼
                              Neon Postgres                     Tavily
                              + pgvector                       web search
```

The agent implements **no integrations of its own**. It discovers its tools from
the MCP server at runtime, so adding a tool there makes it available to the agent
without touching or redeploying the agent.

## Services

| Service | Stack | Port | What it does |
| --- | --- | --- | --- |
| [`services/mcp-server`](services/mcp-server) | Python, `mcp` 2.x | 8080 | Tools: web search, hybrid semantic search, document upload. **Deployed to Cloud Run.** |
| [`services/backend`](services/backend) | FastAPI, `deepagents`, LangGraph | 8000 | Runs the agent loop, streams AG-UI events |
| [`services/frontend`](services/frontend) | Next.js 16, `@ag-ui/client` | 3000 | Chat UI with a live tool-call trace |

One repository, three deploy targets. The MCP server still deploys on its own
with `cd services/mcp-server && ./deploy.sh` — nesting it changed nothing about
that.

## Running it locally

```bash
make install
```

Fill in `services/backend/.env` and `services/mcp-server/.env` from the
`.env.example` next to each, then run three terminals:

```bash
make mcp        # :8080
```

```bash
make backend    # :8000
```

```bash
make frontend   # :3000
```

The backend can point at the **deployed** MCP server instead of a local one —
set `AGENT_MCP_URL` to the Cloud Run URL and `AGENT_MCP_TOKEN` to the Secret
Manager token, and you are running a local agent against production tools.

## How a question flows through it

1. The browser posts an AG-UI `RunAgentInput` to a Next.js route, which proxies
   to the backend. The backend URL and token never reach the browser.
2. The backend fetches the tool list from the MCP server and builds a deep agent
   over it.
3. LangGraph streams events. Each `on_tool_start` becomes AG-UI
   `TOOL_CALL_START` / `ARGS`, each `on_tool_end` a `TOOL_CALL_RESULT`.
4. The UI renders each call as it opens — which tool, what arguments, how long it
   took, what came back — so the agent's reasoning is visible rather than implied.

## Verified compatibility

The three services do not share a dependency set, and one pairing is genuinely
surprising:

- **`langchain-mcp-adapters` pins `mcp` 1.x, while the server runs `mcp` 2.x.**
  These talk over the wire protocol, not the library, and they negotiate fine.
  This was tested end to end: the 1.x client discovers all four tools from the
  2.x server, with schemas intact, and tool calls round-trip.
- OpenRouter serves embeddings as well as chat, despite listing no embedding
  models in its catalogue. Tested: `openai/text-embedding-3-small` returns 1536
  dims through `openrouter.ai/api/v1`.
- Every dependency carries an upper bound at the major it was verified against.

## Model configuration

The agent talks to **OpenRouter**, which speaks the OpenAI API, so the provider
is one env var. The default is `qwen/qwen3.7-flash` — $0.03 / $0.13 per million
tokens with a 1M context, roughly a tenth of a cent per research turn.

The only hard requirement is **tool calling**: a model without it cannot reach
any MCP tool and will quietly answer from memory instead. Alternatives, all
tool-capable:

| Model | $/Mtok in | out | Context |
| --- | --- | --- | --- |
| `mistralai/mistral-nemo` | 0.019 | 0.03 | 131K |
| `qwen/qwen3.7-flash` (default) | 0.030 | 0.13 | 1M |
| `deepseek/deepseek-v4-flash-0731` | 0.040 | 0.08 | 1.3M |
| `openai/gpt-oss-120b` | 0.037 | 0.17 | 131K |
| `openai/gpt-5-mini` | 0.250 | 2.00 | 400K |
| `anthropic/claude-haiku-4.5` | 1.000 | 5.00 | 200K |

**Embeddings go through OpenRouter too** — `openai/text-embedding-3-small`
against `https://openrouter.ai/api/v1`, verified returning 1536 dims. One key
covers the agent and the vector search.
