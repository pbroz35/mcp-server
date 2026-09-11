.PHONY: install test lint mcp backend frontend dev clean

install:
	cd services/mcp-server && python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
	cd services/backend && python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
	cd services/frontend && npm install

test:
	cd services/mcp-server && .venv/bin/pytest -q
	cd services/backend && .venv/bin/pytest -q

lint:
	cd services/mcp-server && .venv/bin/ruff check src tests
	cd services/backend && .venv/bin/ruff check src tests
	cd services/frontend && npx tsc --noEmit

mcp:        ## MCP server on :8080
	cd services/mcp-server && .venv/bin/python -m mcp_server --http --port 8080

backend:    ## agent service on :8000
	cd services/backend && .venv/bin/python -m backend

frontend:   ## UI on :3000
	cd services/frontend && npm run dev

clean:
	rm -rf services/*/.venv services/frontend/node_modules services/frontend/.next
