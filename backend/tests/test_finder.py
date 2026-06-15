"""Tests for the strategy-driven finder engine (parse, query, screen, fallback, ranking).

No Ollama / network / DB: the LLM parse and the live screen are injected via fake functions.
"""
import asyncio

from services.finder import (
    FinderMatch,
    ScreenCandidate,
    build_equity_query,
    load_fallback_universe,
    parse_mandate,
    rank_matches,
    run_screen,
)
from services.nl_target import NLVerdict


def _verdict(matches, strength, llm=None):
    return NLVerdict(matches=matches, strength=strength, reason="", llm_strength=llm)


# ── parse_mandate ────────────────────────────────────────────────────────────────

def test_parse_mandate_maps_and_validates_fields():
    async def fake_parse(mandate):
        return {
            "exchange": "nasdaq",
            "sector": "healthcare",            # lowercase → matched case-insensitively
            "max_market_cap_usd": 15000000000,
            "min_market_cap_usd": None,
            "min_revenue_growth_pct": 20,
            "nl_criterion": "aktuelle Turnaround-Story",
        }

    p = asyncio.run(parse_mandate("Nasdaq Biotech <15B >20% Turnaround", parse_fn=fake_parse))
    assert p.parsed_ok is True
    assert p.filters["exchanges"] == ["NMS"]
    assert p.filters["sector"] == "Healthcare"
    assert p.filters["max_market_cap"] == 15000000000
    assert p.filters["min_revenue_growth"] == 20
    assert "min_market_cap" not in p.filters          # null dropped
    assert p.nl_criterion == "aktuelle Turnaround-Story"


def test_parse_mandate_drops_invalid_sector_and_exchange():
    async def fake_parse(mandate):
        return {"exchange": "frankfurt", "sector": "Biotechnology", "nl_criterion": "x"}

    p = asyncio.run(parse_mandate("…", parse_fn=fake_parse))
    assert "exchanges" not in p.filters               # unknown exchange dropped
    assert "sector" not in p.filters                  # "Biotechnology" is not a valid Yahoo sector
    assert p.parsed_ok is True


def test_parse_mandate_falls_back_when_llm_returns_none():
    async def fake_parse(mandate):
        return None

    p = asyncio.run(parse_mandate("irgendein Mandat", parse_fn=fake_parse))
    assert p.parsed_ok is False
    assert p.filters == {}
    assert p.nl_criterion == "irgendein Mandat"        # whole mandate becomes the NL criterion


def test_parse_mandate_defaults_nl_criterion_to_mandate_when_missing():
    async def fake_parse(mandate):
        return {"sector": "Technology"}                # no nl_criterion key

    p = asyncio.run(parse_mandate("Tech-Wachstumswerte", parse_fn=fake_parse))
    assert p.filters["sector"] == "Technology"
    assert p.nl_criterion == "Tech-Wachstumswerte"


# ── build_equity_query ───────────────────────────────────────────────────────────

def test_build_query_with_all_filters():
    q = build_equity_query({
        "exchanges": ["NMS"], "sector": "Healthcare",
        "max_market_cap": 15e9, "min_revenue_growth": 20,
    })
    # 4 predicates → an AND query whose nested operands carry our fields.
    s = str(q)
    assert "exchange" in s and "Healthcare" in s
    assert "intradaymarketcap" in s and "quarterlyrevenuegrowth.quarterly" in s


def test_build_query_defaults_to_us_region_when_no_filters():
    q = build_equity_query({})
    assert "region" in str(q) and "us" in str(q)


# ── run_screen (injected screen_fn) ──────────────────────────────────────────────

def test_run_screen_maps_rows_to_candidates():
    async def fake_screen(filters, size):
        return [
            {"symbol": "crsp", "shortName": "CRISPR", "marketCap": 5e9, "sector": "Healthcare"},
            {"symbol": "", "shortName": "junk"},          # no ticker → dropped
        ]

    candidates, source = asyncio.run(run_screen({}, screen_fn=fake_screen))
    assert source == "yfinance_screen"
    assert len(candidates) == 1
    assert candidates[0].ticker == "CRSP" and candidates[0].market_cap == 5e9


def test_run_screen_returns_empty_on_failure():
    async def boom(filters, size):
        raise RuntimeError("yahoo down")

    candidates, source = asyncio.run(run_screen({}, screen_fn=boom))
    assert candidates == [] and source == "error"


# ── fallback universe ────────────────────────────────────────────────────────────

def test_fallback_universe_loads_candidates():
    universe = load_fallback_universe()
    assert universe and all(isinstance(c, ScreenCandidate) and c.ticker for c in universe)


# ── ranking ──────────────────────────────────────────────────────────────────────

def test_rank_matches_orders_matched_then_strength():
    a = FinderMatch(ScreenCandidate("AAA", "A"), _verdict(False, 1))
    b = FinderMatch(ScreenCandidate("BBB", "B"), _verdict(True, 3, llm=3))
    c = FinderMatch(ScreenCandidate("CCC", "C"), _verdict(True, 5, llm=4))
    ranked = rank_matches([a, b, c])
    assert [m.candidate.ticker for m in ranked] == ["CCC", "BBB", "AAA"]
