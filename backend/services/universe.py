"""Dynamisches NASDAQ-Biotech-Universum über den NASDAQ Stock Screener (Alt-B Stufe 1).

    NASDAQ gesamt (~4000) ──► Sektor Health Care (~930) ──► Biotech/Pharma (~670)

EIN HTTP-Call auf `api.nasdaq.com/api/screener/stocks` (kein API-Key, nur Browser-User-Agent)
liefert alle NASDAQ-Titel inkl. Sektor/Industrie/Market Cap → Crawl dauert Sekunden statt
~50 min (alter Ansatz: 3000+ Finnhub-`profile2`-Calls). Market Cap wird hier bewusst NICHT
gefiltert — die 15-Mrd-Grenze ist Teil des Alt-B-Scans, nicht des Universums.

Die reinen Filter (`is_biotech_industry`, `parse_screener_market_cap`, `is_common_symbol`)
sind unit-getestet; der Screener-Call ist I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
_SCREENER_HEADERS = {
    # api.nasdaq.com blockt Default-HTTP-Clients — ein Browser-User-Agent genügt.
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}
# Geräte-/Diagnostik-Industrien zählen nicht als Biotech/Pharma-Bezug.
_INDUSTRY_EXCLUDE = ("electromedical", "in vitro")
MIN_UNIVERSE_MARKET_CAP = 150_000_000
_SECURITY_NAME_EXCLUDE = (
    " warrant",
    " warrants",
    " unit",
    " units",
    " right",
    " rights",
    " preferred",
    " preference",
)


@dataclass(frozen=True)
class UniverseStock:
    ticker: str
    name: str
    market_cap: float | None
    industry: str


# ── Reine Filter (testbar) ──────────────────────────────────────────────────────
def is_biotech_industry(sector: str | None, industry: str | None) -> bool:
    """Health Care + Biotech/Pharma-Industrie? (Geräte/Diagnostik bewusst raus)."""
    sec = (sector or "").strip().lower()
    ind = (industry or "").strip().lower()
    if sec != "health care":
        return False
    if any(term in ind for term in _INDUSTRY_EXCLUDE):
        return False
    return ind.startswith("biotechnology:") or "medicinal chemicals" in ind


def parse_screener_market_cap(value) -> float | None:
    """Screener-`marketCap` ("12,345,678.00", "" oder Zahl) → absolute USD."""
    if value in (None, ""):
        return None
    try:
        cap = float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None
    return cap if cap > 0 else None


def is_common_symbol(symbol: str | None) -> bool:
    """Stammaktien-Symbol? (Units/Warrants/Preferred wie "ABC^A" oder "ABC/WS" raus)."""
    s = (symbol or "").strip()
    return bool(s) and not any(ch in s for ch in ("^", "/", " "))


def passes_universe_filters(row: dict) -> bool:
    """NASDAQ-Screener-Zeile gehört ins realistische Alt-B-Biotech-Universum?"""
    ticker = str(row.get("symbol") or "").strip().upper()
    name = f" {str(row.get('name') or '').strip().lower()} "
    if not is_common_symbol(ticker):
        return False
    if any(term in name for term in _SECURITY_NAME_EXCLUDE):
        return False
    if not is_biotech_industry(row.get("sector"), row.get("industry")):
        return False
    market_cap = parse_screener_market_cap(row.get("marketCap"))
    return market_cap is not None and market_cap >= MIN_UNIVERSE_MARKET_CAP


# ── I/O (NASDAQ Stock Screener) ─────────────────────────────────────────────────
async def fetch_nasdaq_screener(client: httpx.AsyncClient) -> list[dict]:
    """Alle NASDAQ-Titel mit Sektor/Industrie/Market Cap — ein einziger Call."""
    resp = await client.get(
        NASDAQ_SCREENER_URL,
        params={"tableonly": "true", "limit": "0", "exchange": "NASDAQ", "download": "true"},
        headers=_SCREENER_HEADERS,
        timeout=60,
    )
    if not resp.is_success:
        return []
    return resp.json().get("data", {}).get("rows") or []


async def crawl_biotech_universe(
    progress: Callable[[int, int, str], Awaitable[None]] | None = None,
) -> list[UniverseStock]:
    """NASDAQ-Biotech/Pharma-Universum aufbauen (Sekunden, ohne Market-Cap-Filter)."""
    async with httpx.AsyncClient(timeout=60) as client:
        rows = await fetch_nasdaq_screener(client)

    out: list[UniverseStock] = []
    for row in rows:
        ticker = str(row.get("symbol") or "").strip().upper()
        if not passes_universe_filters(row):
            continue
        out.append(UniverseStock(
            ticker=ticker,
            name=str(row.get("name") or ticker).strip(),
            market_cap=parse_screener_market_cap(row.get("marketCap")),
            industry=str(row.get("industry") or "").strip(),
        ))
    if progress is not None:
        await progress(len(out), len(out), "Screener-Abruf abgeschlossen")
    return out


# ── Persistenz (screener_universe) ──────────────────────────────────────────────
async def save_universe(db: "AsyncSession", stocks: list[UniverseStock]) -> None:
    """Crawl-Ergebnis als neues Universum ablegen (alter Stand wird ersetzt)."""
    from sqlalchemy import delete

    from models import ScreenerUniverse

    await db.execute(delete(ScreenerUniverse))
    now = datetime.utcnow()
    for s in stocks:
        db.add(ScreenerUniverse(
            ticker=s.ticker, name=s.name, industry=s.industry,
            market_cap=s.market_cap, updated_at=now,
        ))
    await db.commit()


async def load_universe(db: "AsyncSession") -> tuple[list[UniverseStock], datetime | None]:
    """Gecachtes Universum + Stand. Leere Liste, wenn noch nie gecrawlt wurde."""
    from sqlalchemy import select

    from models import ScreenerUniverse

    rows = (await db.execute(select(ScreenerUniverse).order_by(ScreenerUniverse.ticker))).scalars().all()
    stocks = [
        UniverseStock(
            ticker=r.ticker, name=r.name,
            market_cap=float(r.market_cap) if r.market_cap is not None else None,
            industry=r.industry,
        )
        for r in rows
    ]
    updated_at = max((r.updated_at for r in rows), default=None)
    return stocks, updated_at
