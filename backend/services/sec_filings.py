"""SEC EDGAR 8-K als Ereignis-Rückgrat (Alt-B Schicht 2).

Ein 8-K ist die SEC-Pflichtmeldung über *wesentliche Ereignisse*. Vorteile ggü. News-APIs:
lückenlos (gesetzlich), historisch + point-in-time (Filing-Datum), mit angehängter
Original-Pressemitteilung (EX-99.1) als sauberem Input für die Stärke-Klassifikation.

Quelle: data.sec.gov / sec.gov (gratis, kein Key — nur ein User-Agent-Header Pflicht).
Reine Helfer (Item-Parsing/-Typ) sind unit-getestet; die Calls sind I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

import httpx

from services.event_strength import EventClassification, classify_event

SEC_HEADERS = {"User-Agent": "portfaio-research research@portfaio.local"}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# Item-Code → menschliche Kategorie (für Anzeige + groben Prior)
_ITEM_TYPES = {
    "1.01": "Partnerschaft/Vertrag",
    "1.02": "Vertragsende",
    "2.02": "Quartalszahlen",
    "5.02": "Management-Wechsel",
    "7.01": "Regulation FD (oft Daten/Präsentation)",
    "8.01": "Sonstiges Wesentliches (oft klinische Daten/FDA)",
}
# Items, die ein echter Katalysator-Kandidat sein können (Rest = Routine/neutral)
_CATALYST_ITEMS = {"1.01", "7.01", "8.01"}


@dataclass(frozen=True)
class Filing8K:
    ticker: str
    filing_date: str
    items: list[str]
    accession: str
    primary_doc: str
    event_type: str
    catalyst_candidate: bool
    url: str = ""
    press_release: str = ""


# ── Reine Helfer (testbar) ──────────────────────────────────────────────────────
def parse_items(items_str: str | None) -> list[str]:
    """\"7.01,8.01,9.01\" -> ['7.01','8.01','9.01'] (9.01 = nur Exhibit-Anhang)."""
    if not items_str:
        return []
    return [i.strip() for i in str(items_str).split(",") if i.strip()]


def classify_8k_type(items: list[str]) -> str:
    """Gröbste Event-Kategorie aus den Item-Codes (für Anzeige)."""
    for code in items:
        if code in _ITEM_TYPES:
            return _ITEM_TYPES[code]
    return "Sonstiges"


def is_catalyst_candidate(items: list[str]) -> bool:
    """Könnte ein echter Katalysator sein? (Partnerschaft / FD / sonstiges Wesentliches).

    9.01 (nur Exhibits) und reine Management-/Zahlen-Items zählen NICHT als Katalysator.
    """
    return any(code in _CATALYST_ITEMS for code in items)


def parse_recent_signals(recent: dict, from_date: str, to_date: str) -> tuple[bool, bool]:
    """(has_catalyst_8k, has_form4) im Datumsfenster — aus dem submissions-`recent`-Block.

    Vorprüfung für den Scan: EIN submissions-Call liefert 8-K (Event) und Form 4
    (Insider-Aktivität) zugleich; Details werden erst für Treffer nachgeladen.
    """
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    items_list = recent.get("items", [""] * len(forms))
    has_catalyst_8k = has_form4 = False
    for i, form in enumerate(forms):
        d = dates[i] if i < len(dates) else ""
        if not (from_date <= d <= to_date):
            continue
        if form == "8-K" and is_catalyst_candidate(parse_items(items_list[i] if i < len(items_list) else "")):
            has_catalyst_8k = True
        elif form == "4":
            has_form4 = True
        if has_catalyst_8k and has_form4:
            break
    return has_catalyst_8k, has_form4


def strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


# ── I/O (SEC EDGAR) ─────────────────────────────────────────────────────────────
async def fetch_cik_map(client: httpx.AsyncClient) -> dict[str, int]:
    """{TICKER: CIK}. Einmal laden + cachen — ändert sich selten."""
    resp = await client.get(_TICKERS_URL, headers=SEC_HEADERS, timeout=30)
    if not resp.is_success:
        return {}
    return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in resp.json().values()}


async def fetch_8k_filings(
    client: httpx.AsyncClient,
    ticker: str,
    cik: int,
    from_date: str,
    to_date: str,
) -> list[Filing8K]:
    """8-K-Filings im Datumsfenster (point-in-time über das Filing-Datum)."""
    resp = await client.get(_SUBMISSIONS.format(cik=cik), headers=SEC_HEADERS, timeout=30)
    if not resp.is_success:
        return []
    recent = resp.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    out: list[Filing8K] = []
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        d = recent["filingDate"][i]
        if not (from_date <= d <= to_date):
            continue
        items = parse_items(recent.get("items", [""] * len(forms))[i])
        acc = recent["accessionNumber"][i]
        prim = recent["primaryDocument"][i]
        accnd = acc.replace("-", "")
        out.append(Filing8K(
            ticker=ticker.upper(), filing_date=d, items=items, accession=acc,
            primary_doc=prim, event_type=classify_8k_type(items),
            catalyst_candidate=is_catalyst_candidate(items),
            url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accnd}/{prim}",
        ))
    return out


async def fetch_press_release(client: httpx.AsyncClient, cik: int, filing: Filing8K) -> str:
    """Den EX-99.1-Pressetext eines Filings holen (für die Stärke-Klassifikation)."""
    accnd = filing.accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accnd}"
    try:
        idx = (await client.get(f"{base}/index.json", headers=SEC_HEADERS, timeout=30)).json()
        for item in idx["directory"]["item"]:
            if re.search(r"ex.?99", item["name"], re.I):
                html = (await client.get(f"{base}/{item['name']}", headers=SEC_HEADERS, timeout=30)).text
                return strip_html(html)[:2000]
    except Exception:
        return ""
    return ""


async def fetch_recent_signals(
    client: httpx.AsyncClient, ticker: str, cik: int, from_date: str, to_date: str,
) -> tuple[bool, bool]:
    """(has_catalyst_8k, has_form4) — billige Vorprüfung mit einem submissions-Call."""
    try:
        resp = await client.get(_SUBMISSIONS.format(cik=cik), headers=SEC_HEADERS, timeout=30)
    except Exception:
        return False, False
    if not resp.is_success:
        return False, False
    recent = resp.json().get("filings", {}).get("recent", {})
    return parse_recent_signals(recent, from_date, to_date)


# ── Phase 1: 8-K-Pressetext → Stärke-Klassifikation (der "echte" Katalysator) ────
async def fetch_8k_catalysts(
    client: httpx.AsyncClient, ticker: str, cik: int, from_date: str, to_date: str,
) -> list[tuple[Filing8K, EventClassification]]:
    """Katalysator-8-Ks im Fenster → PR-Text klassifiziert (Stärke + Richtung)."""
    out: list[tuple[Filing8K, EventClassification]] = []
    for f in await fetch_8k_filings(client, ticker, cik, from_date, to_date):
        if not f.catalyst_candidate:
            continue
        pr = await fetch_press_release(client, cik, f)
        if not pr:
            continue
        out.append((replace(f, press_release=pr), classify_event(pr, source="SEC 8-K (company press release)")))
    return out


def strongest_catalyst(
    catalysts: list[tuple[Filing8K, EventClassification]],
    min_strength: int = 4,
) -> tuple[Filing8K, EventClassification] | None:
    """Stärkster positiver Katalysator >= min_strength (default 4 = "stark", für den Backtest)."""
    qualifying = [(f, ev) for f, ev in catalysts
                  if ev.direction == "positive" and ev.strength >= min_strength]
    return max(qualifying, key=lambda t: t[1].strength, default=None)
