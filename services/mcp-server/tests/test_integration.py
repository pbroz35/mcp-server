"""Tests that need a real Postgres.

Skipped unless MCP_DATABASE_URL and MCP_OPENAI_API_KEY are set, so the default
suite stays hermetic and offline. Run with:

    MCP_DATABASE_URL=... MCP_OPENAI_API_KEY=... .venv/bin/pytest tests/test_integration.py

These exist because a whole class of bug is invisible without a database: the
JSONB columns came back as strings, which no amount of mocking would have shown.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("MCP_DATABASE_URL") and os.environ.get("MCP_OPENAI_API_KEY")),
    reason="needs a live database and embedding credentials",
)


@pytest.fixture(autouse=True)
async def fresh_pool():
    """Dispose the pool after each test.

    The pool is module-level and binds to the event loop that created it, while
    pytest-asyncio gives each test a new loop — reusing it across tests fails
    with 'Event loop is closed'. Production keeps one loop, so this is a test
    concern only.
    """
    yield
    from mcp_server import db

    await db.close_pool()


@pytest.fixture(autouse=True)
def use_real_settings(monkeypatch):
    """Undo the isolating fixture in conftest for this module."""
    from mcp_server import config

    for field, env in [
        ("database_url", "MCP_DATABASE_URL"),
        ("openai_api_key", "MCP_OPENAI_API_KEY"),
        ("openai_base_url", "MCP_OPENAI_BASE_URL"),
        ("embedding_model", "MCP_EMBEDDING_MODEL"),
    ]:
        value = os.environ.get(env)
        if value:
            monkeypatch.setattr(config.settings, field, value)


async def test_jsonb_metadata_decodes_to_a_dict():
    """asyncpg returns JSONB as a string without a codec, which fails model
    validation inside the tools — the exact bug this guards against."""
    from mcp_server import db

    rows = await db.list_documents(limit=1)
    if not rows:
        pytest.skip("corpus is empty")
    assert isinstance(rows[0]["metadata"], dict), "JSONB came back as a string"


async def test_search_results_build_valid_models():
    """Construct the Pydantic models the tools return, which is where the
    string-vs-dict mismatch actually surfaced."""
    from mcp_server import db
    from mcp_server.ingest import embed_query
    from mcp_server.tools.documents import SearchHit

    embedding = await embed_query("revenue")
    rows = await db.search_chunks(embedding=embedding, query_text="revenue", limit=3)
    for r in rows:
        SearchHit(
            chunk_id=r["id"],
            document_id=r["document_id"],
            document_title=r["title"],
            source=r["source"],
            page=r["page"],
            text=r["text"],
            score=float(r["score"]),
            similarity=float(r["similarity"]) if r["similarity"] is not None else None,
            metadata={**(r["doc_metadata"] or {}), **(r["chunk_metadata"] or {})},
        )


async def test_schema_matches_configured_dimensions():
    """A vector(N) column that disagrees with the embedding model silently
    corrupts every search, so assert they match."""
    from mcp_server import db
    from mcp_server.config import settings

    async with db.connection() as conn:
        col_type = await conn.fetchval(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        )
    assert col_type == f"vector({settings.embedding_dimensions})"


async def test_metadata_filter_excludes_non_matching_documents():
    from mcp_server import db
    from mcp_server.ingest import embed_query

    embedding = await embed_query("anything")
    rows = await db.search_chunks(
        embedding=embedding,
        query_text="anything",
        limit=5,
        metadata_filter={"company": "__no_such_company__"},
    )
    assert rows == []
