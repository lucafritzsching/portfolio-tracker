"""Strategy-driven finder (Alt-B): a free-text *mandate* → live screen → NL-Agent on survivors.

Where ``nl_target`` judges ONE named ticker, the finder *discovers* tickers that match a free-text
strategy. A mandate like
    "Nasdaq Biotech, < 15 Mrd. Market Cap, > 20 % Umsatzwachstum, aktuelle Turnaround-Story"
splits cleanly along Alt-B's whole thesis:

  * the **quantitative** parts (exchange / sector / market-cap / revenue-growth) → a deterministic
    ``yfinance`` equity screen (ONE server-side call; exact; cheap), and
  * the **qualitative** remainder ("aktuelle Turnaround-Story") → the existing NL-Agent
    (``services.nl_target.evaluate_nl_target``) judges each survivor against fresh news.

The LLM only **parses** the mandate (the parse is surfaced in the trace, so it stays auditable) and
**judges** the NL criterion — the screening itself is fully deterministic. Compute stays
MacBook-friendly: the screen is one call and only the top-N survivors ever reach the LLM. If the live
screen is unavailable, the finder falls back to a small curated universe so a demo never goes dark.

This module owns the *pieces* (parse, query, screen, fallback, ranking); the SSE orchestration +
news/DB I/O lives in ``agent.finder_runner`` — mirroring the ``nl_target`` / ``nl_target_runner`` split.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yfinance as yf

from config import settings
from services.nl_target import NLVerdict

# Yahoo exchange codes we accept (mapped from human words in the mandate).
EXCHANGE_MAP = {"nasdaq": "NMS", "nyse": "NYQ", "amex": "ASE"}

# The 11 valid Yahoo sectors — the LLM must map a mandate's industry onto one of these.
VALID_SECTORS = (
    "Basic Materials", "Communication Services", "Consumer Cyclical", "Consumer Defensive",
    "Energy", "Financial Services", "Healthcare", "Industrials", "Real Estate",
    "Technology", "Utilities",
)

DEFAULT_MAX_CANDIDATES = 8   # how many screened survivors reach the LLM (compute budget)
SCREEN_SIZE = 50             # how many rows the screen returns before capping


@dataclass(frozen=True)
class ScreenCandidate:
    ticker: str
    name: str
    market_cap: float | None = None
    sector: str | None = None
    industry: str | None = None


@dataclass
class FinderMatch:
    candidate: ScreenCandidate
    verdict: NLVerdict


@dataclass
class ParsedMandate:
    filters: dict          # {exchanges:[..], sector, max_market_cap, min_market_cap, min_revenue_growth}
    nl_criterion: str      # the qualitative remainder handed to the NL-Agent
    parsed_ok: bool        # True if the LLM produced a usable parse


def _to_float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _extract_json(text: str | None) -> dict | None:
    """Extract the first JSON object from model output; None if absent/invalid."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


# ── 1. Parse the free-text mandate into hard filters + an NL criterion ────────────

def _parse_prompt(mandate: str) -> str:
    sectors = ", ".join(VALID_SECTORS)
    return (
        "Du extrahierst aus einem Freitext-Anlagemandat die harten, quantitativen Filter und das "
        f"qualitative Rest-Kriterium.\n\nMandat: „{mandate}“\n\n"
        "Antworte NUR mit JSON, ohne weiteren Text:\n"
        '{"exchange": "nasdaq"|"nyse"|"amex"|null, '
        f'"sector": <einer von: {sectors} — oder null>, '
        '"max_market_cap_usd": <Zahl in USD oder null>, '
        '"min_market_cap_usd": <Zahl in USD oder null>, '
        '"min_revenue_growth_pct": <Zahl in Prozent, z. B. 20, oder null>, '
        '"nl_criterion": "<qualitatives Rest-Kriterium als kurzer Satz>"}\n'
        "Regeln: Branchen wie 'Biotech'/'Pharma' → sector 'Healthcare'; 'Tech' → 'Technology'. "
        "Marktkapitalisierung in absolute USD (15 Mrd. → 15000000000). "
        "Qualitatives (Turnaround, Insider-Käufe, Momentum, Story) gehört in nl_criterion, NICHT in die Filter. "
        "Nicht genannte Felder: null."
    )


async def _parse_via_ollama(mandate: str) -> dict | None:
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": _parse_prompt(mandate)}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "")
    except Exception:
        return None
    return _extract_json(text)


async def parse_mandate(mandate: str, *, parse_fn=None) -> ParsedMandate:
    """Parse + VALIDATE the mandate. Unknown/invalid fields are dropped (never trusted blindly).

    Falls back to ``filters={}`` + ``nl_criterion=mandate`` when the LLM gives no usable parse, so the
    finder degrades to "judge the whole sentence over a default universe" instead of failing.
    """
    mandate = (mandate or "").strip()
    fn = parse_fn or _parse_via_ollama
    try:
        raw = await fn(mandate)
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return ParsedMandate(filters={}, nl_criterion=mandate, parsed_ok=False)

    filters: dict = {}
    exch = str(raw.get("exchange") or "").strip().lower()
    if exch in EXCHANGE_MAP:
        filters["exchanges"] = [EXCHANGE_MAP[exch]]

    sector = str(raw.get("sector") or "").strip().lower()
    for valid in VALID_SECTORS:
        if valid.lower() == sector:
            filters["sector"] = valid
            break

    mc_max = _to_float(raw.get("max_market_cap_usd"))
    if mc_max and mc_max > 0:
        filters["max_market_cap"] = mc_max
    mc_min = _to_float(raw.get("min_market_cap_usd"))
    if mc_min and mc_min > 0:
        filters["min_market_cap"] = mc_min
    rg = _to_float(raw.get("min_revenue_growth_pct"))
    if rg is not None and rg > 0:
        filters["min_revenue_growth"] = rg

    nl_criterion = str(raw.get("nl_criterion") or "").strip() or mandate
    return ParsedMandate(filters=filters, nl_criterion=nl_criterion, parsed_ok=True)


# ── 2. Build the deterministic equity query + run the live screen ─────────────────

def build_equity_query(filters: dict):
    """Translate validated filters into a yfinance ``EquityQuery``.

    Always anchored to at least one predicate (region=us when no filters), so the query is valid even
    for a sparse mandate; the screen is then capped by market cap, keeping it bounded.
    """
    preds = []
    exchanges = filters.get("exchanges")
    if exchanges:
        preds.append(yf.EquityQuery("is-in", ["exchange", *exchanges]))
    else:
        preds.append(yf.EquityQuery("eq", ["region", "us"]))
    if filters.get("sector"):
        preds.append(yf.EquityQuery("eq", ["sector", filters["sector"]]))
    if filters.get("max_market_cap"):
        preds.append(yf.EquityQuery("lt", ["intradaymarketcap", filters["max_market_cap"]]))
    if filters.get("min_market_cap"):
        preds.append(yf.EquityQuery("gt", ["intradaymarketcap", filters["min_market_cap"]]))
    if filters.get("min_revenue_growth") is not None:
        preds.append(yf.EquityQuery("gte", ["quarterlyrevenuegrowth.quarterly", filters["min_revenue_growth"]]))
    return yf.EquityQuery("and", preds) if len(preds) > 1 else preds[0]


def _row_to_candidate(row: dict) -> ScreenCandidate:
    return ScreenCandidate(
        ticker=str(row.get("symbol") or "").upper(),
        name=str(row.get("shortName") or row.get("longName") or row.get("symbol") or ""),
        market_cap=_to_float(row.get("marketCap")),
        sector=row.get("sector") or row.get("sectorDisp"),
        industry=row.get("industry") or row.get("industryDisp"),
    )


async def _default_screen(filters: dict, size: int) -> list[dict]:
    query = build_equity_query(filters)
    res = await asyncio.to_thread(
        lambda: yf.screen(query, size=size, sortField="intradaymarketcap", sortAsc=False)
    )
    return res.get("quotes", []) if isinstance(res, dict) else []


async def run_screen(filters: dict, *, size: int = SCREEN_SIZE, screen_fn=None) -> tuple[list[ScreenCandidate], str]:
    """Run the live screen. Returns (candidates, source). On any failure returns ([], "error")
    so the caller can fall back to the curated universe."""
    fn = screen_fn or _default_screen
    try:
        rows = await fn(filters, size)
    except Exception:
        return [], "error"
    candidates = [c for c in (_row_to_candidate(r) for r in rows) if c.ticker]
    return candidates, "yfinance_screen"


# ── 3. Offline fallback universe (only when the live screen is unavailable) ───────

def load_fallback_universe() -> list[ScreenCandidate]:
    """A small curated universe used ONLY when the live screen fails — keeps the demo alive offline."""
    path = Path(__file__).resolve().parents[1] / "data" / "biotech_universe.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [
        ScreenCandidate(
            ticker=str(r["ticker"]).upper(),
            name=str(r.get("name") or r["ticker"]),
            industry=str(r.get("industry") or "") or None,
        )
        for r in rows
        if r.get("ticker")
    ]


# ── 4. Rank the NL verdicts ──────────────────────────────────────────────────────

def rank_matches(matches: list[FinderMatch]) -> list[FinderMatch]:
    """Matched first, then by final significance, then by raw LLM strength (stable for ties)."""
    return sorted(
        matches,
        key=lambda m: (m.verdict.matches, m.verdict.strength, m.verdict.llm_strength or 0),
        reverse=True,
    )
