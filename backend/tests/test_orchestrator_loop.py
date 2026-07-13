"""Tests für den Tool-Loop des Orchestrators (_run_agent_loop).

Kein Ollama / Netz: ``httpx.AsyncClient`` wird im ``agent.orchestrator``-Namespace gestubbt.
Kernregression: Die finale Antwort wird aus dem Loop-Response ausgeliefert — es darf KEIN
zweiter Generierungs-Call passieren (POST-Count == 1 bei einer Antwort ohne Tool-Calls).
"""
import asyncio
import json

import agent.orchestrator as orch


def _run(coro):
    return asyncio.run(coro)


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _fake_client_factory(responses: list[dict], post_log: list[dict]):
    """Fake für httpx.AsyncClient: liefert die vorgegebenen /api/chat-Antworten der Reihe nach."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            post_log.append(json)
            return _FakeResponse(responses[len(post_log) - 1])

    return _FakeClient


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return json.dumps({"ok": True})


def test_final_answer_without_tools_uses_single_call(monkeypatch):
    posts: list[dict] = []
    answer = "Die Antwort auf die Frage. " * 10  # > 120 Zeichen → mehrere Chunks
    monkeypatch.setattr(orch.httpx, "AsyncClient", _fake_client_factory(
        [{"message": {"content": answer}, "eval_count": 42, "eval_duration": 2_000_000_000}],
        posts,
    ))

    stats: dict = {}
    executor = _FakeExecutor()

    async def collect():
        return [c async for c in orch._run_agent_loop(
            [{"role": "user", "content": "Frage"}], executor, stats)]

    chunks = _run(collect())
    assert "".join(chunks) == answer
    assert len(posts) == 1                      # Regression: kein zweiter Generierungs-Call
    assert stats.get("eval_count") == 42        # Stats kommen aus dem Loop-Response
    assert executor.calls == []


def test_tool_call_then_final_answer(monkeypatch):
    posts: list[dict] = []
    monkeypatch.setattr(orch.httpx, "AsyncClient", _fake_client_factory(
        [
            {"message": {"content": "", "tool_calls": [
                {"function": {"name": "get_news", "arguments": {"ticker": "AAPL"}}}]}},
            {"message": {"content": "Fazit auf Basis der News."}, "eval_count": 7},
        ],
        posts,
    ))

    executor = _FakeExecutor()
    trace: list = []

    async def collect():
        return [c async for c in orch._run_agent_loop(
            [{"role": "user", "content": "News zu AAPL?"}], executor, {}, trace=trace)]

    chunks = _run(collect())
    text = "".join(chunks)
    assert executor.calls == [("get_news", {"ticker": "AAPL"})]
    assert len(posts) == 2                      # 1× Tool-Runde + 1× finale Antwort, nicht 3
    assert "Fazit auf Basis der News." in text
    assert trace and trace[0]["tool"] == "get_news"


def test_empty_content_falls_back_to_stream(monkeypatch):
    """Leerer Content ohne Tool-Calls (selten) → alter Streaming-Fallback greift."""
    posts: list[dict] = []
    monkeypatch.setattr(orch.httpx, "AsyncClient", _fake_client_factory(
        [{"message": {"content": ""}}], posts))

    async def fake_stream(messages, stats=None):
        yield "Fallback-Antwort"

    monkeypatch.setattr(orch, "_stream_ollama_response", fake_stream)

    async def collect():
        return [c async for c in orch._run_agent_loop(
            [{"role": "user", "content": "?"}], _FakeExecutor(), {})]

    assert "".join(_run(collect())) == "Fallback-Antwort"
