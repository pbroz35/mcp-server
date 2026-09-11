"""Web search via Tavily.

Tavily is used rather than a raw SERP API because it returns extracted page
content, not just links — an agent can cite a passage without a second fetch.
"""

import logging
from typing import Annotated, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from ..config import settings

logger = logging.getLogger(__name__)

TAVILY_ENDPOINT = "https://api.tavily.com/search"


class WebResult(BaseModel):
    title: str
    url: str
    content: str = Field(description="Extracted passage relevant to the query.")
    score: float = Field(description="Tavily's relevance score, 0-1.")
    published_date: str | None = None


class WebSearchResult(BaseModel):
    query: str
    answer: str | None = Field(
        default=None, description="Tavily's own synthesized answer, when requested."
    )
    results: list[WebResult]


def register(mcp: MCPServer) -> None:
    @mcp.tool()
    async def web_search(
        query: Annotated[str, Field(description="Search query, phrased as a question or keywords.")],
        max_results: Annotated[int, Field(description="How many results to return.", ge=1, le=20)] = 5,
        depth: Annotated[
            Literal["basic", "advanced"],
            Field(description="'advanced' reads pages more thoroughly; slower and costs more credits."),
        ] = "basic",
        include_domains: Annotated[
            list[str] | None, Field(description="Restrict results to these domains.")
        ] = None,
        exclude_domains: Annotated[
            list[str] | None, Field(description="Drop results from these domains.")
        ] = None,
    ) -> WebSearchResult:
        """Search the live web for current information.

        Use for recent events, current figures, and anything outside the
        uploaded document corpus. For material already uploaded, prefer
        search_documents — it is faster, free, and cites exact pages.
        """
        if not settings.web_search_enabled:
            raise ToolError("Web search is unavailable: MCP_TAVILY_API_KEY is not configured.")

        payload: dict = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": depth,
            "include_answer": True,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(TAVILY_ENDPOINT, json=payload)
            if response.status_code == 401:
                raise ToolError("Tavily rejected the API key.")
            if response.status_code == 429:
                raise ToolError("Tavily rate limit reached; retry shortly.")
            response.raise_for_status()
            data = response.json()

        logger.info("web_search %r -> %d results", query, len(data.get("results", [])))
        return WebSearchResult(
            query=query,
            answer=data.get("answer"),
            results=[
                WebResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    # Results are third-party page text. Everything downstream
                    # treats it as data, never as instructions.
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                    published_date=r.get("published_date"),
                )
                for r in data.get("results", [])
            ],
        )
