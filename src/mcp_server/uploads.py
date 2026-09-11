"""HTTP upload endpoint for adding documents to the corpus.

Uploads are an HTTP route rather than an MCP tool on purpose: MCP tool
arguments are JSON, so a PDF would have to be base64-encoded into the model's
context — expensive, size-limited, and pointless, since a human is doing the
uploading, not the model. The model's job starts after ingestion, at
search_documents.

The route sits behind the same bearer-token middleware as /mcp.
"""

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from . import db
from .config import settings
from .ingest import chunk_pages, chunk_text, clean_text, embed_texts, extract_pdf, sha256_bytes

logger = logging.getLogger(__name__)

TEXT_TYPES = {"text/plain", "text/markdown", "application/json", ""}


async def upload_document(request: Request) -> JSONResponse:
    """POST /documents — multipart upload of a PDF or text file.

    Fields:
      file      (required) the document
      title     (optional) defaults to the filename
      source    (optional) a URL or citation string
      metadata  (optional) JSON object stored for later filtering
    """
    if not settings.documents_enabled:
        return JSONResponse(
            {"error": "Document ingestion is not configured (MCP_DATABASE_URL, MCP_OPENAI_API_KEY)."},
            status_code=503,
        )

    try:
        form = await request.form()
    except Exception as exc:  # noqa: BLE001 - any parse failure is the client's, so 400 not 500
        return JSONResponse({"error": f"Malformed multipart body: {exc}"}, status_code=400)

    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": "Missing 'file' field."}, status_code=400)

    data = await upload.read()
    if not data:
        return JSONResponse({"error": "Uploaded file is empty."}, status_code=400)
    if len(data) > settings.max_upload_bytes:
        return JSONResponse(
            {"error": f"File exceeds {settings.max_upload_bytes} bytes."}, status_code=413
        )

    filename = getattr(upload, "filename", None) or "untitled"
    content_type = (getattr(upload, "content_type", None) or "").split(";")[0].strip()
    title = str(form.get("title") or filename)
    source = form.get("source")
    source = str(source) if source else None

    raw_metadata = form.get("metadata")
    metadata: dict = {}
    if raw_metadata:
        try:
            metadata = json.loads(str(raw_metadata))
        except json.JSONDecodeError as exc:
            return JSONResponse({"error": f"metadata is not valid JSON: {exc}"}, status_code=400)
        if not isinstance(metadata, dict):
            return JSONResponse({"error": "metadata must be a JSON object."}, status_code=400)

    # --- extract -------------------------------------------------------
    is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")
    try:
        if is_pdf:
            pages = extract_pdf(data)
            if not pages:
                return JSONResponse(
                    {
                        "error": "No extractable text found. If this is a scanned PDF it needs "
                        "OCR first — this server does not perform OCR."
                    },
                    status_code=422,
                )
            chunks = chunk_pages(pages)
            page_count = pages[-1][0]
            content_type = "application/pdf"
        elif content_type in TEXT_TYPES or filename.lower().endswith((".txt", ".md")):
            text = clean_text(data.decode("utf-8", errors="replace"))
            if not text.strip():
                return JSONResponse({"error": "File contains no text."}, status_code=422)
            chunks = chunk_text(text)
            page_count = None
            content_type = content_type or "text/plain"
        else:
            return JSONResponse(
                {"error": f"Unsupported content type {content_type!r}. Supported: PDF, text, markdown."},
                status_code=415,
            )
    except Exception as exc:
        logger.exception("extraction failed for %s", filename)
        return JSONResponse({"error": f"Could not read the file: {exc}"}, status_code=422)

    if not chunks:
        return JSONResponse({"error": "Document produced no chunks."}, status_code=422)

    # --- embed and store ------------------------------------------------
    try:
        vectors = await embed_texts([c.text for c in chunks])
    except Exception as exc:
        logger.exception("embedding failed for %s", filename)
        return JSONResponse({"error": f"Embedding failed: {exc}"}, status_code=502)

    document_id, is_new = await db.upsert_document(
        title=title,
        source=source,
        content_type=content_type,
        sha256=sha256_bytes(data),
        page_count=page_count,
        metadata=metadata,
    )
    stored = await db.replace_chunks(
        document_id,
        [
            {
                "ordinal": c.ordinal,
                "page": c.page,
                "text": c.text,
                "embedding": v,
                "metadata": c.metadata,
            }
            for c, v in zip(chunks, vectors, strict=True)
        ],
    )

    logger.info(
        "ingested %s -> document %d (%d chunks, %s)",
        filename, document_id, stored, "new" if is_new else "replaced",
    )
    return JSONResponse(
        {
            "document_id": document_id,
            "title": title,
            "chunks": stored,
            "pages": page_count,
            "replaced_existing": not is_new,
            "metadata": metadata,
        },
        status_code=201 if is_new else 200,
    )
