"""Translate LangGraph's event stream into AG-UI protocol events.

This is what makes the agent's work visible: every MCP tool call becomes a
TOOL_CALL_START/ARGS/RESULT triple the frontend renders live.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from ag_ui.core import (
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

logger = logging.getLogger(__name__)


def _text_of(chunk: Any) -> str:
    """Pull plain text out of a message chunk.

    Content is a string on simple replies but a list of typed blocks when
    thinking or tool use is in play, so text has to be filtered out of it.
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _serialize(value: Any) -> str:
    """Render a tool result as text the UI can show."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


async def translate(
    stream: AsyncIterator[dict[str, Any]], *, thread_id: str, run_id: str
) -> AsyncIterator[Any]:
    """Yield AG-UI events for one agent run.

    RUN_STARTED and exactly one terminal event (RUN_FINISHED or RUN_ERROR) always
    bracket the stream, because the frontend uses them to leave its loading state.
    """
    yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id)

    open_message: str | None = None
    open_tools: set[str] = set()

    try:
        async for event in stream:
            kind = event.get("event")
            data = event.get("data") or {}

            if kind == "on_chat_model_stream":
                text = _text_of(data.get("chunk"))
                if not text:
                    continue
                if open_message is None:
                    open_message = event.get("run_id") or run_id
                    yield TextMessageStartEvent(
                        type=EventType.TEXT_MESSAGE_START, message_id=open_message, role="assistant"
                    )
                yield TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT, message_id=open_message, delta=text
                )

            elif kind == "on_tool_start":
                # Close any open message first: a tool call interrupts the prose,
                # and leaving the message open would nest the two in the UI.
                if open_message is not None:
                    yield TextMessageEndEvent(
                        type=EventType.TEXT_MESSAGE_END, message_id=open_message
                    )
                    open_message = None

                tool_call_id = event.get("run_id") or ""
                open_tools.add(tool_call_id)
                yield ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tool_call_id,
                    tool_call_name=event.get("name") or "tool",
                )
                yield ToolCallArgsEvent(
                    type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool_call_id,
                    delta=_serialize(data.get("input")),
                )
                yield ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id)

            elif kind == "on_tool_end":
                tool_call_id = event.get("run_id") or ""
                open_tools.discard(tool_call_id)
                yield ToolCallResultEvent(
                    type=EventType.TOOL_CALL_RESULT,
                    message_id=f"{tool_call_id}-result",
                    tool_call_id=tool_call_id,
                    content=_serialize(data.get("output")),
                    role="tool",
                )

        if open_message is not None:
            yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=open_message)

        yield RunFinishedEvent(
            type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id
        )

    except Exception as exc:
        logger.exception("agent run %s failed", run_id)
        # Close anything still open, or the UI shows a spinner forever.
        if open_message is not None:
            yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=open_message)
        for tool_call_id in open_tools:
            yield ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id)
        yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(exc))
