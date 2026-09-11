"""Postgres + pgvector access.

The corpus lives in two tables: `documents` (one row per uploaded file or
fetched page) and `chunks` (the embedded, searchable pieces). Metadata is a
JSONB column on both, so a caller can filter on arbitrary keys without a
migration — the point of the whole design is that you can upload a PDF tagged
`{"company": "NVDA", "form": "10-K", "year": 2025}` and filter on it later.
"""

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from .config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id           BIGSERIAL PRIMARY KEY,
    title        TEXT NOT NULL,
    source       TEXT,
    content_type TEXT NOT NULL DEFAULT 'application/pdf',
    -- sha256 of the raw bytes: re-uploading the same file updates the existing
    -- row instead of silently duplicating every chunk into search results.
    sha256       TEXT NOT NULL UNIQUE,
    page_count   INTEGER,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    page        INTEGER,
    text        TEXT NOT NULL,
    embedding   vector({dims}) NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    -- Generated, so keyword search can never drift out of sync with the text.
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_metadata_idx ON chunks USING gin (metadata);
CREATE INDEX IF NOT EXISTS documents_metadata_idx ON documents USING gin (metadata);
"""


async def get_pool() -> asyncpg.Pool:
    """Lazily create the connection pool.

    Lazy rather than lifespan-managed so the same code path works under stdio,
    under uvicorn, and in tests. Cloud Run cold-starts a container per burst of
    traffic, so the pool is deliberately small.
    """
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError("MCP_DATABASE_URL is not set — document tools are disabled.")
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=0,
            max_size=5,
            # Neon's pooled endpoint runs pgbouncer in transaction mode, where
            # server-side prepared statements are not safe to reuse across
            # checkouts. Without this, asyncpg raises DuplicatePreparedStatement
            # under concurrency — intermittently, which is the worst kind.
            statement_cache_size=0,
            command_timeout=30,
        )
        logger.info("database pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def connection():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def init_schema() -> None:
    """Apply the schema. Idempotent, so it is safe to run on every deploy."""
    async with connection() as conn:
        await conn.execute(SCHEMA_SQL.format(dims=settings.embedding_dimensions))
    logger.info("schema applied")


def to_vector_literal(embedding: list[float]) -> str:
    """pgvector's text input format.

    asyncpg has no native codec for the vector type, so values cross the wire
    as a string and are cast in SQL with `$n::vector`.
    """
    return "[" + ",".join(f"{x:.7g}" for x in embedding) + "]"


async def upsert_document(
    *,
    title: str,
    source: str | None,
    content_type: str,
    sha256: str,
    page_count: int | None,
    metadata: dict[str, Any],
) -> tuple[int, bool]:
    """Insert or update a document by content hash.

    Returns (document_id, is_new). When the same bytes are uploaded again the
    existing row is reused and its chunks are replaced, so the corpus never
    accumulates duplicates of the same file under different titles.
    """
    async with connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (title, source, content_type, sha256, page_count, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (sha256) DO UPDATE
                SET title = EXCLUDED.title,
                    source = EXCLUDED.source,
                    page_count = EXCLUDED.page_count,
                    metadata = EXCLUDED.metadata
            RETURNING id, (xmax = 0) AS is_new
            """,
            title, source, content_type, sha256, page_count, json.dumps(metadata),
        )
        return row["id"], row["is_new"]


async def replace_chunks(document_id: int, chunks: list[dict[str, Any]]) -> int:
    """Atomically swap in a document's chunks.

    Delete-then-insert inside one transaction: a re-upload never leaves the
    document half-indexed, and concurrent searches see either the old set or
    the new one, never a mix.
    """
    async with connection() as conn, conn.transaction():
        await conn.execute("DELETE FROM chunks WHERE document_id = $1", document_id)
        await conn.executemany(
            """
                INSERT INTO chunks (document_id, ordinal, page, text, embedding, metadata)
                VALUES ($1, $2, $3, $4, $5::vector, $6::jsonb)
                """,
            [
                (
                    document_id,
                    c["ordinal"],
                    c.get("page"),
                    c["text"],
                    to_vector_literal(c["embedding"]),
                    json.dumps(c.get("metadata", {})),
                )
                for c in chunks
            ],
        )
    return len(chunks)


async def search_chunks(
    *,
    embedding: list[float],
    query_text: str,
    limit: int = 8,
    metadata_filter: dict[str, Any] | None = None,
    document_ids: list[int] | None = None,
    semantic_only: bool = False,
) -> list[dict[str, Any]]:
    """Hybrid search: vector similarity fused with keyword relevance.

    Pure vector search misses exact terms (a ticker, a statute number, a proper
    noun the embedding smooths away); pure keyword search misses paraphrase.
    Results from both are combined with Reciprocal Rank Fusion, which needs no
    score normalization between two incomparable scales — it only uses rank.

    `metadata_filter` is applied with the JSONB containment operator, so
    {"company": "NVDA"} matches any chunk whose document metadata contains that
    pair, and filtering happens before ranking rather than after.
    """
    vec = to_vector_literal(embedding)
    # Over-fetch per arm so fusion has room to reorder; RRF over two top-8 lists
    # would mostly reproduce the vector ranking.
    candidates = max(limit * 4, 20)
    meta_json = json.dumps(metadata_filter) if metadata_filter else None

    sql = """
    WITH filtered AS (
        SELECT c.id, c.document_id, c.ordinal, c.page, c.text, c.embedding, c.tsv,
               d.title, d.source, d.metadata AS doc_metadata
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE ($3::jsonb IS NULL OR d.metadata @> $3::jsonb)
          AND ($4::bigint[] IS NULL OR c.document_id = ANY($4::bigint[]))
    ),
    vector_hits AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1::vector) AS rank,
               1 - (embedding <=> $1::vector) AS similarity
        FROM filtered
        ORDER BY embedding <=> $1::vector
        LIMIT $5
    ),
    keyword_hits AS (
        SELECT id, ROW_NUMBER() OVER (
                   ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', $2)) DESC
               ) AS rank
        FROM filtered
        WHERE $6 = FALSE
          AND websearch_to_tsquery('english', $2) @@ tsv
        ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', $2)) DESC
        LIMIT $5
    ),
    fused AS (
        SELECT COALESCE(v.id, k.id) AS id,
               -- RRF with k=60, the value from the original paper. The constant
               -- damps the influence of the very top ranks so one arm cannot
               -- dominate the fusion.
               COALESCE(1.0 / (60 + v.rank), 0) + COALESCE(1.0 / (60 + k.rank), 0) AS score,
               v.similarity
        FROM vector_hits v
        FULL OUTER JOIN keyword_hits k ON k.id = v.id
    )
    SELECT f.id, f.score, f.similarity, c.document_id, c.ordinal, c.page, c.text,
           c.metadata AS chunk_metadata, d.title, d.source, d.metadata AS doc_metadata
    FROM fused f
    JOIN chunks c ON c.id = f.id
    JOIN documents d ON d.id = c.document_id
    ORDER BY f.score DESC
    LIMIT $7
    """
    async with connection() as conn:
        rows = await conn.fetch(
            sql, vec, query_text, meta_json, document_ids, candidates, semantic_only, limit
        )
    return [dict(r) for r in rows]


async def list_documents(
    *, limit: int = 50, metadata_filter: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    meta_json = json.dumps(metadata_filter) if metadata_filter else None
    async with connection() as conn:
        rows = await conn.fetch(
            """
            SELECT d.id, d.title, d.source, d.content_type, d.page_count,
                   d.metadata, d.created_at,
                   (SELECT count(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
            FROM documents d
            WHERE ($1::jsonb IS NULL OR d.metadata @> $1::jsonb)
            ORDER BY d.created_at DESC
            LIMIT $2
            """,
            meta_json, limit,
        )
    return [dict(r) for r in rows]


async def get_chunk_window(chunk_id: int, before: int = 1, after: int = 1) -> list[dict[str, Any]]:
    """Fetch a chunk plus its neighbours.

    A search hit is a fragment; an agent citing it usually needs the sentences
    on either side to quote it fairly. Neighbours come from the same document
    by ordinal, so this never crosses a document boundary.
    """
    async with connection() as conn:
        rows = await conn.fetch(
            """
            WITH target AS (SELECT document_id, ordinal FROM chunks WHERE id = $1)
            SELECT c.id, c.ordinal, c.page, c.text, d.title, d.source, d.metadata AS doc_metadata
            FROM chunks c
            JOIN target t ON c.document_id = t.document_id
            JOIN documents d ON d.id = c.document_id
            WHERE c.ordinal BETWEEN t.ordinal - $2 AND t.ordinal + $3
            ORDER BY c.ordinal
            """,
            chunk_id, before, after,
        )
    return [dict(r) for r in rows]


async def delete_document(document_id: int) -> bool:
    async with connection() as conn:
        result = await conn.execute("DELETE FROM documents WHERE id = $1", document_id)
    return result.endswith("1")


async def corpus_stats() -> dict[str, Any]:
    async with connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT (SELECT count(*) FROM documents) AS documents,
                   (SELECT count(*) FROM chunks) AS chunks,
                   (SELECT max(created_at) FROM documents) AS latest
            """
        )
    return dict(row)
