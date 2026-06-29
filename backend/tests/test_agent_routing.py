"""Tests for the agent routing loop (orchestrator) with Ollama fully mocked.

The live `/ask` path runs `_run_agent_loop`, which talks to Ollama via httpx. Here we replace
the HTTP client with canned responses so we can assert the routing behaviour deterministically:
the LLM's tool call is dispatched to the executor, captured in the trace, and the final answer
is streamed back. No network, no DB, no real model.
"""
import asyncio
import json

import agent.orchestrator as orch
from agent.orchestrator import _extract_text_tool_calls, ask_stream, _run_agent_loop


# ── Fake Ollama HTTP client ──────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """Async-context client that pops canned responses from a shared queue per .post()."""
    def __init__(self, queue):
        self._queue = queue

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        return _FakeResp(self._queue.pop(0))


def _patch_ollama(monkeypatch, responses):
    queue = list(responses)
    monkeypatch.setattr(orch.httpx, "AsyncClient", lambda *a, **k: _FakeClient(queue))
    return queue


def _msg(content="", tool_calls=None):
    m = {"message": {"content": content}}
    if tool_calls is not None:
        m["message"]["tool_calls"] = tool_calls
    return m


def _tool_call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return json.dumps({"ok": True, "tool": name})


# ── Text tool-call fallback (pure) ───────────────────────────────────────────────

def test_extract_text_tool_calls_parses_valid_json_line():
    content = 'Etwas Text\n{"name": "judge_news", "arguments": {"ticker": "CRNX"}}\n'
    calls = _extract_text_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "judge_news"
    assert calls[0]["function"]["arguments"] == {"ticker": "CRNX"}


def test_extract_text_tool_calls_ignores_non_tool_text():
    assert _extract_text_tool_calls("nur eine normale Antwort ohne Tool") == []
    assert _extract_text_tool_calls("") == []


# ── Routing loop: tool dispatch + trace ──────────────────────────────────────────

def test_agent_loop_dispatches_tool_and_records_trace(monkeypatch):
    # Turn 1 → LLM asks for a tool; turn 2 → no tool (decide final); turn 3 → final text.
    _patch_ollama(monkeypatch, [
        _msg(tool_calls=[_tool_call("judge_news", {"ticker": "CRNX", "criterion": "Turnaround"})]),
        _msg(content=""),                       # no tool_calls → loop finalizes
        _msg(content="FINALE ANTWORT"),         # fetched by _fetch_ollama_response
    ])
    executor = _FakeExecutor()
    trace: list = []

    async def _run():
        out = ""
        async for chunk in _run_agent_loop(
            [{"role": "user", "content": "prüf CRNX"}],
            executor, show_tools=True, stream_final=False, trace=trace,
        ):
            out += chunk
        return out

    out = asyncio.run(_run())

    assert executor.calls == [("judge_news", {"ticker": "CRNX", "criterion": "Turnaround"})]
    assert len(trace) == 1 and trace[0]["tool"] == "judge_news"
    assert "🔧" in out                # visible tool-trace marker
    assert "FINALE ANTWORT" in out


def test_agent_loop_malformed_tool_args_become_empty_dict(monkeypatch):
    # Arguments arriving as a non-JSON string must not crash the loop (→ {} fallback).
    _patch_ollama(monkeypatch, [
        _msg(tool_calls=[_tool_call("get_news", "NICHT-JSON")]),
        _msg(content=""),
        _msg(content="fertig"),
    ])
    executor = _FakeExecutor()

    async def _run():
        return "".join([c async for c in _run_agent_loop(
            [{"role": "user", "content": "x"}], executor, stream_final=False,
        )])

    asyncio.run(_run())
    assert executor.calls == [("get_news", {})]


# ── ask_stream end-to-end (direct answer, no tool) ───────────────────────────────

def test_ask_stream_direct_answer_appends_trace_suffix(monkeypatch):
    _patch_ollama(monkeypatch, [_msg(content="")])  # iter 1: no tool_calls → stream final

    async def _fake_stream(messages, stats=None):
        yield "Hallo Welt"
    monkeypatch.setattr(orch, "_stream_ollama_response", _fake_stream)

    async def _run():
        return "".join([c async for c in ask_stream("Was geht?", db=None, current_prices={}, history=[])])

    out = asyncio.run(_run())
    assert "Hallo Welt" in out
    assert "␞TRACE␞" in out
    payload = json.loads(out.split("␞TRACE␞", 1)[1])
    assert payload["question"] == "Was geht?" and payload["trace"] == []


def test_ask_stream_empty_question_short_circuits():
    out = "".join(list(_drain(ask_stream("   ", db=None))))
    assert "Keine Frage" in out


def _drain(agen):
    """Synchronously collect an async generator (helper for trivial, mock-free cases)."""
    async def _c():
        return [x async for x in agen]
    return asyncio.run(_c())
