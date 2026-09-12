import pytest

from backend import config

# Settings read .env, so without this the suite depends on local configuration.
ISOLATED = {
    "openrouter_api_key": "",
    "mcp_token": "",
    "mcp_url": "http://127.0.0.1:8080/mcp",
}


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    """Reset every environment-dependent setting before each test."""
    for field, value in ISOLATED.items():
        monkeypatch.setattr(config.settings, field, value)
