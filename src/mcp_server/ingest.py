"""Turning a file into searchable chunks: extract -> chunk -> embed.

Kept separate from the tool and HTTP layers so the pipeline can be tested
without a database, a network, or an MCP client.
"""

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import tiktoken
from openai import AsyncOpenAI

from .config import settings

logger = logging.getLogger(__name__)

_encoder = None
_client: AsyncOpenAI | None = None


def _get_encoder():
    """Load the tokenizer once. tiktoken fetches its vocabulary on first use
    and caches it on disk, so this is slow exactly once per container."""
    global _encoder
    if _encoder is None:
        try:
            _encoder = tiktoken.encoding_for_model(settings.embedding_model)
        except KeyError:
            # Unknown model name (a newer embedding model, or a custom one):
            # cl100k_base is the right family and only affects chunk sizing.
            _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("MCP_OPENAI_API_KEY is not set — embeddings are unavailable.")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


@dataclass
class Chunk:
    ordinal: int
    text: str
    page: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf(data: bytes) -> list[tuple[int, str]]:
    """Extract text per page. Returns [(page_number, text), ...], 1-indexed.

    Page numbers are carried all the way through to search results so a
    citation can say "page 34" rather than pointing at an opaque chunk id.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one bad page must not fail the whole upload
            logger.warning("page %d extraction failed: %s", i, exc)
            text = ""
        if text.strip():
            pages.append((i, clean_text(text)))
    return pages


def clean_text(text: str) -> str:
    """Normalize extracted text.

    PDF extraction produces hyphenated line breaks, hard-wrapped paragraphs,
    and runs of whitespace. Left alone these poison both the embedding and the
    keyword index: "rev-\\nenue" matches neither "revenue" nor anything else.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)      # de-hyphenate across lines
    text = re.sub(r"(?<![\n.])\n(?![\n•\-*\d])", " ", text)  # unwrap soft breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(
    text: str,
    *,
    page: int | None = None,
    start_ordinal: int = 0,
    max_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[Chunk]:
    """Split text into token-bounded chunks on paragraph boundaries.

    Splitting on paragraphs first and only falling back to a hard token cut for
    oversized paragraphs keeps semantic units intact — a chunk that ends
    mid-sentence embeds poorly and reads badly when quoted back as a citation.
    """
    max_tokens = max_tokens or settings.chunk_tokens
    overlap_tokens = overlap_tokens or settings.chunk_overlap_tokens
    enc = _get_encoder()

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        body = "\n\n".join(buffer).strip()
        if body:
            chunks.append(Chunk(ordinal=start_ordinal + len(chunks), text=body, page=page))
        buffer, buffer_tokens = [], 0

    for para in paragraphs:
        tokens = len(enc.encode(para))

        if tokens > max_tokens:
            # A single oversized paragraph (a table, a dense legal block):
            # flush what we have, then cut it into overlapping windows.
            flush()
            ids = enc.encode(para)
            step = max(max_tokens - overlap_tokens, 1)
            for start in range(0, len(ids), step):
                window = ids[start : start + max_tokens]
                if not window:
                    break
                chunks.append(
                    Chunk(
                        ordinal=start_ordinal + len(chunks),
                        text=enc.decode(window).strip(),
                        page=page,
                    )
                )
                if start + max_tokens >= len(ids):
                    break
            continue

        if buffer_tokens + tokens > max_tokens:
            flush()
        buffer.append(para)
        buffer_tokens += tokens

    flush()
    return chunks


def chunk_pages(pages: list[tuple[int, str]]) -> list[Chunk]:
    """Chunk a whole document, keeping ordinals contiguous across pages."""
    all_chunks: list[Chunk] = []
    for page_no, text in pages:
        all_chunks.extend(chunk_text(text, page=page_no, start_ordinal=len(all_chunks)))
    return all_chunks


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch. Returns vectors in the same order as the input."""
    if not texts:
        return []
    client = _get_client()
    vectors: list[list[float]] = []
    # The API caps how much it accepts per request; batching also bounds the
    # blast radius of a retry.
    batch_size = 96
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
            dimensions=settings.embedding_dimensions,
        )
        # The API documents order preservation, but sorting by index makes that
        # an assertion rather than an assumption — a silent misalignment here
        # would attach every vector to the wrong chunk.
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
