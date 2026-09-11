import json

import pytest
from ag_ui.core import EventType
from fastapi.testclient import TestClient

from backend.app import app, to_langchain_messages
from backend.events import _serialize, _text_of, translate


class FakeChunk:
    """Stands in for an AIMessageChunk."""

    def __init__(self, content):
        self.content = content


async def drain(events):
    return [e async for e in events]


async def stream_of(items):
    for item in items:
        yield item


# --- text extraction ------------------------------------------------------


def test_text_of_plain_string():
    assert _text_of(FakeChunk("hello")) == "hello"


def test_text_of_block_list_keeps_only_text():
    """With thinking on, content is a block list; only text blocks are shown."""
    chunk = FakeChunk(
        [
            {"type": "thinking", "thinking": "internal reasoning"},
            {"type": "text", "text": "visible answer"},
        ]
    )
    assert _text_of(chunk) == "visible answer"


def test_text_of_handles_missing_content():
    assert _text_of(FakeChunk(None)) == ""


def test_serialize_falls_back_on_unserializable():
    assert _serialize({"a": 1}) == '{"a": 1}'
    assert _serialize("plain") == "plain"
    assert "object" in _serialize(object()) or _serialize(object())


# --- event translation ----------------------------------------------------


async def test_run_is_bracketed_by_started_and_finished():
    events = await drain(translate(stream_of([]), thread_id="t1", run_id="r1"))
    assert events[0].type == EventType.RUN_STARTED
    assert events[-1].type == EventType.RUN_FINISHED


async def test_tool_call_produces_start_args_end_result():
    """This sequence is what the UI renders as 'the agent is calling X'."""
    source = [
        {
            "event": "on_tool_start",
            "name": "search_documents",
            "run_id": "tool-1",
            "data": {"input": {"query": "revenue"}},
        },
        {
            "event": "on_tool_end",
            "name": "search_documents",
            "run_id": "tool-1",
            "data": {"output": {"hits": []}},
        },
    ]
    events = await drain(translate(stream_of(source), thread_id="t", run_id="r"))
    types = [e.type for e in events]
    assert types == [
        EventType.RUN_STARTED,
        EventType.TOOL_CALL_START,
        EventType.TOOL_CALL_ARGS,
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.RUN_FINISHED,
    ]
    start = events[1]
    assert start.tool_call_name == "search_documents"
    assert json.loads(events[2].delta) == {"query": "revenue"}


async def test_text_is_opened_once_and_closed_before_a_tool_call():
    """Leaving a message open across a tool call would nest them in the UI."""
    source = [
        {"event": "on_chat_model_stream", "run_id": "m1", "data": {"chunk": FakeChunk("Let me ")}},
        {"event": "on_chat_model_stream", "run_id": "m1", "data": {"chunk": FakeChunk("search.")}},
        {"event": "on_tool_start", "name": "web_search", "run_id": "tool-9", "data": {"input": {}}},
    ]
    events = await drain(translate(stream_of(source), thread_id="t", run_id="r"))
    types = [e.type for e in events]
    assert types.count(EventType.TEXT_MESSAGE_START) == 1
    assert types.index(EventType.TEXT_MESSAGE_END) < types.index(EventType.TOOL_CALL_START)


async def test_empty_chunks_do_not_open_a_message():
    source = [{"event": "on_chat_model_stream", "run_id": "m", "data": {"chunk": FakeChunk("")}}]
    events = await drain(translate(stream_of(source), thread_id="t", run_id="r"))
    assert all(e.type != EventType.TEXT_MESSAGE_START for e in events)


async def test_failure_closes_open_blocks_and_emits_run_error():
    """A crash mid-stream must not leave the UI spinning forever."""

    async def exploding():
        yield {
            "event": "on_chat_model_stream",
            "run_id": "m1",
            "data": {"chunk": FakeChunk("partial")},
        }
        yield {"event": "on_tool_start", "name": "web_search", "run_id": "t9", "data": {"input": {}}}
        raise RuntimeError("upstream exploded")

    events = await drain(translate(exploding(), thread_id="t", run_id="r"))
    types = [e.type for e in events]
    assert types[-1] == EventType.RUN_ERROR
    assert "upstream exploded" in events[-1].message
    # The text block opened before the tool call was closed by the tool handler.
    assert types.count(EventType.TEXT_MESSAGE_END) == 1


# --- HTTP surface ---------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


def test_health_reports_configuration(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model"] == "claude-opus-5"
    assert body["configured"] is False  # no key in tests


def test_message_conversion_keeps_user_and_assistant_turns():
    class M:
        def __init__(self, role, content):
            self.role, self.content = role, content

    converted = to_langchain_messages(
        [M("user", "hi"), M("assistant", "hello"), M("tool", "{}"), M("assistant", "")]
    )
    assert [m.content for m in converted] == ["hi", "hello"]


def test_agent_endpoint_reports_missing_key_as_run_error(client):
    """Unconfigured must surface as a RUN_ERROR event, not a 500."""
    # camelCase because that is the wire shape the AG-UI client sends.
    response = client.post(
        "/agent",
        json={
            "threadId": "t1",
            "runId": "r1",
            "messages": [{"id": "1", "role": "user", "content": "hello"}],
            "tools": [],
            "context": [],
            "state": {},
            "forwardedProps": {},
        },
    )
    assert response.status_code == 200
    assert "RUN_ERROR" in response.text
    assert "AGENT_ANTHROPIC_API_KEY" in response.text
