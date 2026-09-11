import pytest
from starlette.testclient import TestClient

from mcp_server.app import create_app
from mcp_server.server import mcp


async def test_tools_are_registered():
    names = {tool.name for tool in await mcp.list_tools()}
    assert "echo" in names


async def test_prompts_are_registered():
    names = {prompt.name for prompt in await mcp.list_prompts()}
    assert "summarize" in names


@pytest.fixture
def client(monkeypatch):
    from mcp_server import app as app_module

    monkeypatch.setattr(app_module.settings, "auth_token", "test-token")
    # The context manager runs the app lifespan, which starts the MCP session
    # manager's task group — without it every /mcp request 500s.
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_is_open(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_mcp_endpoint_rejects_missing_token(client):
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 401


def test_mcp_endpoint_rejects_wrong_token(client):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


async def test_echo_tool_runs():
    result = await mcp.call_tool("echo", {"message": "hello"})
    assert "hello" in str(result)


def test_initialize_with_valid_token(client):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        headers={
            "Authorization": "Bearer test-token",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert "mcp-server" in response.text
