"""FastAPI service exposing the deep agent over the AG-UI protocol.

POST /agent takes an AG-UI RunAgentInput and streams back AG-UI events as SSE.
"""

import logging
import uuid

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from .agent import build_agent
from .config import settings
from .events import translate

logging.basicConfig(
    level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="research-agent-backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def to_langchain_messages(messages) -> list:
    """Convert AG-UI messages into LangChain ones, keeping only what the agent
    needs: tool traffic is replayed by the graph, not by the client."""
    converted = []
    for m in messages:
        role = getattr(m, "role", None)
        content = getattr(m, "content", None) or ""
        if role == "user":
            converted.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            converted.append(AIMessage(content=content))
    return converted


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "model": settings.model,
            "base_url": settings.base_url,
            "mcp_url": settings.mcp_url,
            # Surface configuration in the probe, so a bad deploy is visible here
            # rather than in a failing run.
            "configured": settings.configured,
            "mcp_token_set": bool(settings.mcp_token),
        }
    )


@app.get("/tools")
async def tools() -> JSONResponse:
    """What the agent can currently do, straight from the MCP server."""
    from .agent import load_tools

    try:
        discovered = await load_tools()
    except Exception as exc:  # noqa: BLE001 - report the reason instead of a 500
        return JSONResponse({"error": str(exc), "tools": []}, status_code=502)
    return JSONResponse(
        {"tools": [{"name": t.name, "description": t.description} for t in discovered]}
    )


@app.post("/agent")
async def run_agent(input_data: RunAgentInput, request: Request):
    """Run the agent and stream AG-UI events."""
    encoder = EventEncoder(accept=request.headers.get("accept"))
    thread_id = input_data.thread_id or str(uuid.uuid4())
    run_id = input_data.run_id or str(uuid.uuid4())

    async def event_stream():
        if not settings.configured:
            from ag_ui.core import EventType, RunErrorEvent

            yield encoder.encode(
                RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message="AGENT_OPENROUTER_API_KEY is not set.",
                )
            )
            return

        agent = await build_agent()
        stream = agent.astream_events(
            {"messages": to_langchain_messages(input_data.messages)},
            version="v2",
            config={"recursion_limit": settings.max_tool_iterations},
        )
        async for event in translate(stream, thread_id=thread_id, run_id=run_id):
            yield encoder.encode(event)

    # StreamingResponse, not EventSourceResponse: the AG-UI encoder already
    # emits complete "data: {...}\n\n" frames, which sse-starlette would wrap again.
    return StreamingResponse(
        event_stream(),
        media_type=encoder.get_content_type(),
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
