"""Trace recorder for the chat tool-use loop.

Accumulates one chat request's activity (rounds, tool calls, tokens, timings) and
persists it as one `chat_traces` row + N `tool_call_traces` rows. This is a
deliberately *stateful* accumulator — instrumentation collecting spans across an
async streaming loop is the one place mutation is the idiomatic shape.
"""

import json
import time
import uuid
from typing import Any

from app.db import AsyncSessionLocal
from app.models.traces import ChatTrace, ToolCallTrace


class TraceRecorder:
    def __init__(self, model: str, request_messages: list[dict]) -> None:
        self.trace_id = uuid.uuid4()
        self._start = time.perf_counter()
        self.model = model
        self.request_messages = request_messages
        self.user_query = _last_user_message(request_messages)
        self.n_rounds = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self.stop_reason: str | None = None
        self.final_answer: str = ""
        self.status: str = "ok"
        self.error_message: str | None = None
        self._tool_calls: list[ToolCallTrace] = []

    def add_round(self, usage: Any, stop_reason: str | None) -> None:
        self.n_rounds += 1
        self.stop_reason = stop_reason
        if usage is not None:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0
            self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
            self.cache_creation_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def add_tool(self, round_index: int, name: str, tool_input: Any, tool_output: Any, duration_ms: int) -> None:
        result_count = len(tool_output) if isinstance(tool_output, list) else None
        self._tool_calls.append(ToolCallTrace(
            id=uuid.uuid4(),
            trace_id=self.trace_id,
            round_index=round_index,
            tool_name=name,
            tool_input=_jsonable(tool_input),
            tool_output=_jsonable(tool_output),
            result_count=result_count,
            duration_ms=duration_ms,
        ))

    def finish(self, final_answer: str, status: str) -> None:
        self.final_answer = final_answer
        self.status = status

    def fail(self, message: str) -> None:
        self.status = "error"
        self.error_message = message

    async def persist(self) -> None:
        duration_ms = int((time.perf_counter() - self._start) * 1000)
        trace = ChatTrace(
            trace_id=self.trace_id,
            user_query=self.user_query,
            request_messages=_jsonable(self.request_messages),
            final_answer=self.final_answer,
            model=self.model,
            n_rounds=self.n_rounds,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_creation_tokens=self.cache_creation_tokens,
            stop_reason=self.stop_reason,
            status=self.status,
            error_message=self.error_message,
            duration_ms=duration_ms,
        )
        trace.tool_calls = self._tool_calls
        async with AsyncSessionLocal() as session:
            session.add(trace)
            await session.commit()


def _last_user_message(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            return content if isinstance(content, str) else json.dumps(content, default=str)
    return ""


def _jsonable(obj: Any) -> Any:
    """Coerce to JSON-serialisable form for JSONB (handles datetimes etc.)."""
    return json.loads(json.dumps(obj, default=str))
