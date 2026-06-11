"""Tests for the free-text NL-target stream (NewsCache -> NLItem -> rendered verdict)."""
import asyncio
from types import SimpleNamespace

from agent import nl_target_runner as runner
from services.nl_target import NLVerdict


def _drain(gen):
    async def collect():
        return "".join([chunk async for chunk in gen])
    return asyncio.run(collect())


def test_stream_renders_verdict_and_trace(monkeypatch):
    async def fake_news(ticker, db, days=14):
        return [SimpleNamespace(headline="XYZ Positive Phase 2 Data", summary="", source="GlobeNewswire")]

    async def fake_eval(criterion, items, ticker="", name="", mode="fast"):
        # one headline in, mapped to an NLItem
        assert len(items) == 1 and items[0].text.startswith("XYZ")
        return NLVerdict(matches=True, strength=4, reason="stark", evidence=["XYZ Positive Phase 2 Data"],
                         source="llm", regex_strength=3, llm_strength=5, mode=mode)

    monkeypatch.setattr(runner, "fetch_and_store_news", fake_news)
    monkeypatch.setattr(runner, "evaluate_nl_target", fake_eval)

    out = _drain(runner.nl_target_stream("turnaround", "XYZ", db=None, mode="agentic"))
    assert "NL-Ziel-Analyse: XYZ" in out
    assert "Urteil" in out and "4/5" in out and "✅ Ja" in out
    assert "agentic" in out and "5/5" in out   # llm raw strength surfaced in the trace


def test_stream_handles_no_news(monkeypatch):
    async def fake_news(ticker, db, days=14):
        return []
    monkeypatch.setattr(runner, "fetch_and_store_news", fake_news)
    out = _drain(runner.nl_target_stream("turnaround", "XYZ", db=None))
    assert "Keine aktuellen Schlagzeilen" in out


def test_stream_requires_criterion():
    out = _drain(runner.nl_target_stream("   ", "XYZ", db=None))
    assert "Kein Kriterium" in out
