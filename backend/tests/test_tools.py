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
        return ParsedMandate(filters={"exchanges": ["NMS"], "min_revenue_growth": 15},
                             nl_criterion="Turnaround", parsed_ok=True)

    async def fake_screen(filters):
        return ([ScreenCandidate("CRSP", "CRISPR", market_cap=5e9)], "yfinance_screen")

    async def fake_enrich(self, ticker):
        return (5e9, 0.30, 25.0, "CRISPR Therapeutics")   # mcap, revenueGrowth(frac), pe, name

    monkeypatch.setattr("agent.tools.parse_mandate", fake_parse)
    monkeypatch.setattr("agent.tools.run_screen", fake_screen)
    monkeypatch.setattr(ToolExecutor, "_enrich", fake_enrich)
    out = json.loads(_run(_ex().execute("screen_by_strategy", {"mandate": "Nasdaq Biotech >15%"})))
    assert out["source"] == "yfinance_screen" and out["nl_criterion"] == "Turnaround"
    c = out["candidates"][0]
    assert c["ticker"] == "CRSP" and c["market_cap_bn"] == 5.0 and c["revenue_growth_pct"] == 30.0


def test_screen_refilters_on_real_revenue_growth(monkeypatch):
    """The enriched annual growth is re-checked against the mandate, so a candidate the live screen
    returned but which actually misses the threshold is dropped — visible + traceable."""
    async def fake_parse(mandate):
        return ParsedMandate(filters={"min_revenue_growth": 15}, nl_criterion="x", parsed_ok=True)

    async def fake_screen(filters):
        return ([ScreenCandidate("HI", "High"), ScreenCandidate("LO", "Low")], "yfinance_screen")

    async def fake_enrich(self, ticker):
        return (2e9, (0.40 if ticker == "HI" else 0.05), None, ticker)   # HI 40% vs LO 5%

    monkeypatch.setattr("agent.tools.parse_mandate", fake_parse)
    monkeypatch.setattr("agent.tools.run_screen", fake_screen)
    monkeypatch.setattr(ToolExecutor, "_enrich", fake_enrich)
    out = json.loads(_run(_ex().execute("screen_by_strategy", {"mandate": "x"})))
    tickers = [c["ticker"] for c in out["candidates"]]
    assert "HI" in tickers and "LO" not in tickers


def test_screen_falls_back_when_empty(monkeypatch):
    async def fake_parse(mandate):
        return ParsedMandate(filters={}, nl_criterion="x", parsed_ok=False)

    async def empty_screen(filters):
        return ([], "error")

    async def fake_enrich(self, ticker):
        return (1e9, 0.20, None, ticker)

    monkeypatch.setattr("agent.tools.parse_mandate", fake_parse)
    monkeypatch.setattr("agent.tools.run_screen", empty_screen)
    monkeypatch.setattr(ToolExecutor, "_enrich", fake_enrich)
    out = json.loads(_run(_ex().execute("screen_by_strategy", {"mandate": "x"})))
    assert out["source"] == "fallback_universe" and out["match_count"] >= 1


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
