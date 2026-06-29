"""Tests for agent-run persistence (chat history + full trace) and quick-stats persistence."""
import asyncio
import json

import agent.orchestrator as orch
from agent.data_science import ModelForecast
from agent.orchestrator import ask_stream
from database import engine, Base, AsyncSessionLocal
from models import AgentRun, AnalysisResult
from repositories.agent_repo import create_run, get_run, list_recent_runs, save_quick_stats
from sqlalchemy import select


async def _reset():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


# ── Repository round-trips ───────────────────────────────────────────────────────

def test_create_run_roundtrip_preserves_full_trace():
    long_result = "X" * 5000  # well beyond the 2500-char frontend truncation
    trace = [{"step": 1, "tool": "judge_news", "args": {"ticker": "CRNX"}, "result": long_result}]

    async def _run():
        await _reset()
        async with AsyncSessionLocal() as db:
            run = await create_run(db, question="q", answer="a", model="m", trace=trace,
                                   total_ms=1234, eval_tokens=10, tokens_per_sec=5.5)
            rid = run.id
        async with AsyncSessionLocal() as db:
            return await get_run(db, rid), await list_recent_runs(db)

    got, recent = asyncio.run(_run())
    assert got is not None
    assert got.question == "q" and got.answer == "a" and got.total_ms == 1234
    assert got.trace[0]["tool"] == "judge_news"
    assert got.trace[0]["result"] == long_result   # untruncated in the DB
    assert len(recent) == 1 and recent[0].id == got.id


def test_save_quick_stats_writes_analysis_results():
    async def _run():
        await _reset()
        arima = ModelForecast("ARIMA(2,1,2)", 1.0, 2.0, 0.5, "BUY", "arima-details")
        ml = ModelForecast("RandomForest", None, None, 0.7, "HOLD", "rf-details")
        async with AsyncSessionLocal() as db:
            row = await save_quick_stats(db, "AAPL", arima, ml)
            rid = row.id
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(AnalysisResult).where(AnalysisResult.id == rid))).scalar_one()

    got = asyncio.run(_run())
    assert got.ticker == "AAPL" and got.model == "arima+rf"
    payload = json.loads(got.analysis_text)
    assert payload["arima"]["signal"] == "BUY"
    assert payload["random_forest"]["signal"] == "HOLD"


# ── ask_stream persistence (Ollama + tools mocked) ───────────────────────────────

class _FakeResp:
    def __init__(self, payload): self._payload = payload
    def raise_for_status(self): pass
    def json(self): return self._payload


class _FakeClient:
    def __init__(self, queue): self._queue = queue
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False
    async def post(self, url, json=None): return _FakeResp(self._queue.pop(0))


class _FakeExecutor:
    def __init__(self, db=None, current_prices=None): pass
    async def execute(self, name, arguments): return "R" * 4000  # long → tests untruncated persistence


def test_ask_stream_persists_run_with_full_trace(monkeypatch):
    queue = [
        {"message": {"content": "", "tool_calls": [
            {"function": {"name": "judge_news", "arguments": {"ticker": "CRNX"}}}]}},
        {"message": {"content": ""}},   # no tool_calls → finalize
    ]
    monkeypatch.setattr(orch.httpx, "AsyncClient", lambda *a, **k: _FakeClient(queue))
    monkeypatch.setattr(orch, "ToolExecutor", _FakeExecutor)

    async def _fake_stream(messages, stats=None):
        yield "Finale Antwort"
    monkeypatch.setattr(orch, "_stream_ollama_response", _fake_stream)

    async def _run():
        await _reset()
        async with AsyncSessionLocal() as db:
            out = "".join([c async for c in ask_stream("prüf CRNX", db=db, current_prices={}, history=[])])
        async with AsyncSessionLocal() as db:
            runs = (await db.execute(select(AgentRun))).scalars().all()
        return out, runs

    out, runs = asyncio.run(_run())

    # Frontend event truncates the tool result; the DB keeps it whole.
    trace_payload = json.loads(out.split("␞TRACE␞", 1)[1])
    assert len(trace_payload["trace"][0]["result"]) == 2500

    assert len(runs) == 1
    run = runs[0]
    assert run.question == "prüf CRNX"
    assert "Finale Antwort" in run.answer
    assert run.trace[0]["tool"] == "judge_news"
    assert len(run.trace[0]["result"]) == 4000   # untruncated in the DB
