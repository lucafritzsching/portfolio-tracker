"""Tests für die neuen Router-Tools (screen_by_strategy, judge_news) + den Dispatcher.

Kein Ollama / Netz / DB: die Engines (parse_mandate/run_screen, fetch_and_store_news/evaluate_nl_target)
werden im ``agent.tools``-Namespace gestubbt. Geprüft: Registrierung, Dispatch, Fehlerbehandlung
(Traceback wird geloggt, JSON-Fehler zurück), Output-Form und der Fallback-Pfad des Screens.
"""
import asyncio
import json

from agent.tools import ToolExecutor, TOOL_DEFINITIONS
from services.finder import ParsedMandate, ScreenCandidate
from services.nl_target import NLVerdict


def _run(coro):
    return asyncio.run(coro)


def _ex():
    return ToolExecutor(db=None, current_prices={})


def test_new_tools_registered():
    names = [d["function"]["name"] for d in TOOL_DEFINITIONS]
    assert "screen_by_strategy" in names and "judge_news" in names


def test_execute_unknown_tool_returns_error():
    out = json.loads(_run(_ex().execute("does_not_exist", {})))
    assert "error" in out


def test_execute_catches_handler_exception(monkeypatch):
    async def boom(mandate):
        raise RuntimeError("kaputt")
    monkeypatch.setattr("agent.tools.parse_mandate", boom)
    out = json.loads(_run(_ex().execute("screen_by_strategy", {"mandate": "x"})))
    assert "error" in out and "kaputt" in out["error"]


def test_screen_by_strategy_shape(monkeypatch):
    async def fake_parse(mandate):
        return ParsedMandate(filters={"exchanges": ["NMS"]}, nl_criterion="Turnaround", parsed_ok=True)

    async def fake_screen(filters):
        return ([ScreenCandidate("CRSP", "CRISPR", market_cap=5e9)], "yfinance_screen")

    monkeypatch.setattr("agent.tools.parse_mandate", fake_parse)
    monkeypatch.setattr("agent.tools.run_screen", fake_screen)
    out = json.loads(_run(_ex().execute("screen_by_strategy", {"mandate": "Nasdaq Biotech ..."})))
    assert out["source"] == "yfinance_screen"
    assert out["nl_criterion"] == "Turnaround"
    assert out["candidates"][0]["ticker"] == "CRSP"
    assert out["candidates"][0]["market_cap_bn"] == 5.0


def test_screen_falls_back_when_empty(monkeypatch):
    async def fake_parse(mandate):
        return ParsedMandate(filters={}, nl_criterion="x", parsed_ok=False)

    async def empty_screen(filters):
        return ([], "error")

    monkeypatch.setattr("agent.tools.parse_mandate", fake_parse)
    monkeypatch.setattr("agent.tools.run_screen", empty_screen)
    out = json.loads(_run(_ex().execute("screen_by_strategy", {"mandate": "x"})))
    assert out["source"] == "fallback_universe" and out["candidate_count"] >= 1


def test_judge_news_no_news(monkeypatch):
    async def no_news(ticker, db, days=14):
        return []
    monkeypatch.setattr("agent.tools.fetch_and_store_news", no_news)
    out = json.loads(_run(_ex().execute("judge_news", {"ticker": "AAPL", "criterion": "Turnaround"})))
    assert out["matches"] is False and "message" in out


def test_judge_news_shape(monkeypatch):
    class _News:
        headline = "AAPL Announces Positive Phase 3 Topline Results"
        summary = ""
        source = "GlobeNewswire"

    async def fake_news(ticker, db, days=14):
        return [_News()]

    async def fake_eval(criterion, items, ticker="", name="", mode="fast"):
        assert items and items[0].text  # the headline made it through
        return NLVerdict(matches=True, strength=4, reason="stark", evidence=["AAPL ..."],
                         source="llm", llm_strength=5)

    async def fake_name(self, ticker):
        return "Apple Inc"

    monkeypatch.setattr("agent.tools.fetch_and_store_news", fake_news)
    monkeypatch.setattr("agent.tools.evaluate_nl_target", fake_eval)
    monkeypatch.setattr(ToolExecutor, "_company_name", fake_name)  # stay offline (no yfinance call)
    out = json.loads(_run(_ex().execute("judge_news", {"ticker": "aapl", "criterion": "Turnaround-Story"})))
    assert out["ticker"] == "AAPL" and out["matches"] is True and out["significance"] == 4
    assert out["trace"]["llm_strength"] == 5 and out["trace"]["final"] == 4
    assert out["trace"]["n_evidence_cited"] == 1 and out["trace"]["source"] == "llm"
