"""Turning a file into searchable chunks: extract -> chunk -> embed.

Separate from the tool and HTTP layers so it tests without a database or network.
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
    """Load the tokenizer once; tiktoken fetches its vocabulary on first use."""
    global _encoder
    if _encoder is None:
        try:
            _encoder = tiktoken.encoding_for_model(settings.embedding_model)
        except KeyError:
            # Unknown model name; cl100k_base is the right family and only
            # affects chunk sizing.
            _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("MCP_OPENAI_API_KEY is not set — embeddings are unavailable.")
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
        )
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
    """Extract text per page as [(page_number, text), ...], 1-indexed. Page
    numbers reach search results so a citation can name a page."""
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
    """Normalize extracted text. PDF extraction leaves hyphenated line breaks
    and hard wrapping, which poison both the embedding and the keyword index."""
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
    """Split text into token-bounded chunks on paragraph boundaries. A chunk
    ending mid-sentence embeds poorly and reads badly when quoted."""
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
            # An oversized paragraph (a table, a dense legal block) has to be
            # cut into overlapping windows.
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
    # The API caps input per request, and batching bounds a retry's cost.
    batch_size = 96
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = await client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
            dimensions=settings.embedding_dimensions,
        )
        # Sort by index rather than trusting order: a misalignment here would
        # attach every vector to the wrong chunk, silently.
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
