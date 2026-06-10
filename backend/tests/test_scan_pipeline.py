"""Funnel-Test für den gestuften Alt-B-Scan (alle Fetches gestubbt, kein Netz/DB/LLM)."""
import asyncio
import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import services.screener as scr
import services.universe as universe_mod
from services.event_llm import LLMEvent
from services.event_strength import classify_event
from services.universe import UniverseStock

PRICES = [40 + i * 0.3 for i in range(160)]


def _prices():
    today = date(2026, 6, 9)
    n = len(PRICES)
    return [SimpleNamespace(date=today - timedelta(days=(n - 1 - i)), close=PRICES[i]) for i in range(n)]


# BIGC fliegt schon am Screener-Cap-Vorfilter raus; NOSI am EDGAR-Gate.
# Fundamentals werden nur noch für EDGAR-Treffer geholt (GOOD + SHRK).
_FUNDAMENTALS = {
    "SHRK": SimpleNamespace(market_cap=2e9, revenue_growth=-0.1),    # Umsatz schrumpft
    "GOOD": SimpleNamespace(market_cap=2e9, revenue_growth=None),    # Pre-Revenue + Signal
}


def test_scan_funnel_counts_and_persistence(monkeypatch):
    fake_md = types.ModuleType("services.market_data")

    async def fundamentals(ticker, db):
        return _FUNDAMENTALS[ticker]

    async def prices(ticker, db, period="1y"):
        return _prices()

    async def news(ticker, db, days=7):
        return [SimpleNamespace(
            headline=f"{ticker} Receives FDA Approval for Lead Drug",
            summary="", source="GlobeNewswire",
            published_at=datetime(2026, 6, 7), sentiment=None,
        )]

    fake_md.fetch_and_store_fundamentals = fundamentals
    fake_md.fetch_and_store_prices = prices
    fake_md.fetch_and_store_news = news
    monkeypatch.setitem(sys.modules, "services.market_data", fake_md)

    async def load_universe(db):
        stocks = [
            UniverseStock("BIGC", "Big Corp", 20e9, "Biotechnology"),
            UniverseStock("SHRK", "Shrink Bio", 2e9, "Biotechnology"),
            UniverseStock("NOSI", "No Signal Bio", 2e9, "Biotechnology"),
            UniverseStock("GOOD", "Good Bio", 2e9, "Biotechnology"),
        ]
        return stocks, datetime(2026, 6, 1)

    monkeypatch.setattr(universe_mod, "load_universe", load_universe)

    async def cik_map(client):
        return {"NOSI": 111, "GOOD": 222, "SHRK": 333}

    async def recent_signals(client, ticker, cik, frm, to):
        return (False, True) if ticker in ("GOOD", "SHRK") else (False, False)

    async def catalysts(client, ticker, cik, frm, to):
        return []

    async def insiders(ticker, days=7, min_value=50_000):
        return [scr.InsiderBuy("CEO", date(2026, 6, 5), date(2026, 6, 6), 1000, 100.0)]

    async def llm(text, ticker="", name=""):
        return LLMEvent(classify_event(text), "", "", used_llm=False)

    monkeypatch.setattr(scr, "fetch_cik_map", cik_map)
    monkeypatch.setattr(scr, "fetch_recent_signals", recent_signals)
    monkeypatch.setattr(scr, "fetch_8k_catalysts", catalysts)
    monkeypatch.setattr(scr, "fetch_insider_buys", insiders)
    monkeypatch.setattr(scr, "classify_event_llm", llm)

    saved = {}

    async def save_run(db, response):
        saved["response"] = response

    monkeypatch.setattr(scr, "save_run", save_run)

    events = []

    async def progress(event):
        events.append(event)

    response = asyncio.run(scr.run_alt_b_scan(db=None, limit=12, min_score=0, progress=progress))

    funnel = {step.label: step.count for step in response.filter_funnel}
    assert funnel["Universum"] == 4
    assert funnel["Market Cap <= 15 Mrd."] == 3          # BIGC raus (Screener-Cap-Vorfilter)
    assert funnel["EDGAR-Vorprüfung"] == 2               # GOOD + SHRK haben Form 4
    assert funnel["Umsatz ok (inkl. Pre-Revenue)"] == 1  # SHRK schrumpft, GOOD (None) bleibt
    assert funnel["7-Tage-Signal"] == 1
    assert funnel["Score-Filter"] == 1

    assert [c.ticker for c in response.candidates] == ["GOOD"]
    good = response.candidates[0]
    assert good.alt_b.qualifies
    assert good.alt_b.score == 80  # FDA-News (50) + Insider (30), kein Umsatz-Bonus
    assert good.alt_b.event_type == "FDA Approval"
    assert good.alt_b.event_strength == 5
    assert good.research.insider_context.total_value == 100_000
    assert good.research.bull_case
    assert good.research.bear_case
    assert good.research.event_timeline[0].event_type == "FDA Approval"
    assert response.universe_source == "live"

    assert saved["response"] is response
    stages = {e["stage"] for e in events}
    assert {"EDGAR-Vorprüfung", "Detail + LLM"} <= stages


def test_scan_uses_only_cached_universe_and_does_not_fallback_to_curated(monkeypatch):
    fake_md = types.ModuleType("services.market_data")
    async def unexpected_fetch(*args, **kwargs):
        raise AssertionError("market data should not be fetched for an empty universe")

    fake_md.fetch_and_store_fundamentals = unexpected_fetch
    fake_md.fetch_and_store_prices = unexpected_fetch
    fake_md.fetch_and_store_news = unexpected_fetch
    monkeypatch.setitem(sys.modules, "services.market_data", fake_md)

    async def load_universe(db):
        return [], None

    monkeypatch.setattr(universe_mod, "load_universe", load_universe)
    monkeypatch.setattr(scr, "load_biotech_universe", lambda: (_ for _ in ()).throw(AssertionError("curated fallback used")))

    saved = {}

    async def save_run(db, response):
        saved["response"] = response

    monkeypatch.setattr(scr, "save_run", save_run)

    response = asyncio.run(scr.run_alt_b_scan(db=None, limit=12, min_score=0))

    assert response.universe_count == 0
    assert response.candidates == []
    assert response.universe_source == "live"
    assert response.filter_funnel[0].detail == "kein gecachtes Universum — bitte Universum aktualisieren"
    assert saved["response"] is response
