.PHONY: install dev test lint run serve docker deploy

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src tests

run:            ## stdio transport (what a local MCP client speaks)
	.venv/bin/python -m mcp_server

serve:          ## HTTP transport on :8080
	.venv/bin/python -m mcp_server --http

docker:
	docker build -t mcp-server . && docker run --rm -p 8080:8080 --env-file .env mcp-server

deploy:
	./deploy.sh
