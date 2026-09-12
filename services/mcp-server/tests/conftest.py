import pytest

from mcp_server import config

# Settings read .env, so without this the suite passes or fails depending on
# whatever keys happen to be configured locally.
ISOLATED = {
    "auth_token": "",
    "database_url": "",
    "openai_api_key": "",
    "openai_base_url": "",
    "tavily_api_key": "",
    "allowed_hosts": "",
}


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    """Reset every environment-dependent setting before each test."""
    for field, value in ISOLATED.items():
        monkeypatch.setattr(config.settings, field, value)
