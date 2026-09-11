FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# One install layer: with no lock file there is nothing to cache separately.
# If rebuild time starts to hurt, add a pinned requirements.txt and install it
# in its own COPY/RUN pair before this.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 1001 app
USER app

# Cloud Run sets PORT; 8080 is the local default.
ENV PORT=8080
EXPOSE 8080

# Single worker: Cloud Run scales by adding instances, not processes, and the
# MCP session manager's task group is per-process.
CMD exec uvicorn mcp_server.app:app --host 0.0.0.0 --port ${PORT}
