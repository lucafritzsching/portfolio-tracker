"""Strategy-driven finder stream for the Alt-B UI section.

Given a free-text *mandate*, stream: the LLM-parsed filters (auditable) → the deterministic
``yfinance`` screen funnel → a per-candidate NL judgment (the existing NL-Agent) as each lands →
a ranked result with full trace. The expensive LLM step runs only on the top-N screened survivors,
so this stays MacBook-friendly. See ``services.finder`` for the underlying pieces.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from services.finder import (
    DEFAULT_MAX_CANDIDATES,
    FinderMatch,
    parse_mandate,
    rank_matches,
    run_screen,
    load_fallback_universe,
)
from services.market_data import fetch_and_store_news
from services.nl_target import NLItem, NLVerdict, evaluate_nl_target


def _headline_text(news_item) -> str:
    headline = (getattr(news_item, "headline", "") or "").strip()
    summary = (getattr(news_item, "summary", "") or "").strip()
    return f"{headline}. {summary}".strip() if summary else headline


def _fmt_cap(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1e9:.2f} Mrd. USD"


def _render_filters(parsed) -> str:
    f = parsed.filters
    lines = ["### Interpretiertes Mandat (LLM-Parse — nachvollziehbar)\n"]
    exch = ", ".join(f["exchanges"]) if f.get("exchanges") else "alle (US)"
    lines.append(f"- **Börse:** {exch}")
    lines.append(f"- **Sektor:** {f.get('sector') or 'beliebig'}")
    if f.get("max_market_cap"):
        lines.append(f"- **Market Cap:** < {_fmt_cap(f['max_market_cap'])}")
    if f.get("min_market_cap"):
        lines.append(f"- **Market Cap:** > {_fmt_cap(f['min_market_cap'])}")
    if f.get("min_revenue_growth") is not None:
        lines.append(f"- **Umsatzwachstum:** ≥ {f['min_revenue_growth']:.0f} %")
    lines.append(f"- **NL-Kriterium (für den Agenten):** „{parsed.nl_criterion}“")
    src = "LLM" if parsed.parsed_ok else "Fallback (Mandat = NL-Kriterium, keine harten Filter)"
    lines.append(f"- **Parse-Quelle:** {src}")
    return "\n".join(lines) + "\n\n"


def _render_results(ranked: list[FinderMatch], nl_criterion: str, source: str) -> str:
    matched = [m for m in ranked if m.verdict.matches]
    others = [m for m in ranked if not m.verdict.matches]

    lines = ["### Treffer (rangiert)\n"]
    if not matched:
        lines.append(f"_Kein Kandidat erfüllt „{nl_criterion}“ aktuell._\n")
    for rank, m in enumerate(matched, start=1):
        c = m.candidate
        lines.append(
            f"**{rank}. {c.ticker} — {c.name}**  ·  Signifikanz {m.verdict.strength}/5  ·  ✅ erfüllt"
        )
        if c.market_cap is not None:
            lines.append(f"  - Market Cap: {_fmt_cap(c.market_cap)}")
        if m.verdict.reason:
            lines.append(f"  - Begründung: {m.verdict.reason}")
        for ev in m.verdict.evidence[:2]:
            lines.append(f"  - Beleg: {ev}")
        lines.append(
            f"  - Trace: Regex-Basis {m.verdict.regex_strength}/5"
            + (f" · LLM-Roh {m.verdict.llm_strength}/5 → final {m.verdict.strength}/5 (Clamp ±1)"
               if m.verdict.llm_strength is not None else " · rein deterministisch")
        )

    if others:
        lines.append("\n**Geprüft, aber (noch) kein Treffer:**")
        lines.append(
            ", ".join(f"{m.candidate.ticker} ({m.verdict.source})" for m in others)
        )

    lines.append("\n### Nachvollziehbarkeit (Trace)\n")
    src_label = {
        "yfinance_screen": "Live-Screen (yfinance, serverseitig gefiltert)",
        "fallback_universe": "Offline-Fallback (kuratiertes Universum)",
    }.get(source, source)
    lines.append(f"- **Kandidaten-Quelle:** {src_label}")
    lines.append("- **Harte Filter:** deterministisch (Yahoo serverseitig) — das LLM beurteilt NUR das NL-Kriterium.")
    lines.append("- **Pro Treffer:** Regex-Basis vs. LLM-Rohstärke → final (geklammert ±1, Anti-Halluzination).")
    return "\n".join(lines) + "\n"


async def finder_stream(
    mandate: str,
    db: AsyncSession,
    mode: str = "fast",
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> AsyncGenerator[str, None]:
    """Stream a strategy-driven finder run: parse → screen → per-candidate NL judgment → ranked."""
    mode = "agentic" if str(mode).lower() == "agentic" else "fast"
    mandate = (mandate or "").strip()
    if not mandate:
        yield "_Kein Mandat angegeben._\n"
        return
    max_candidates = max(1, min(15, int(max_candidates)))

    yield "## Strategie-Finder\n\n"
    yield f"**Mandat:** „{mandate}“  ·  **Modus:** {mode}\n\n"

    # 1. Parse the mandate (LLM) → hard filters + NL criterion.
    parsed = await parse_mandate(mandate)
    yield _render_filters(parsed)

    # 2. Deterministic live screen (falls back to a curated universe if Yahoo is unavailable).
    candidates, source = await run_screen(parsed.filters)
    if not candidates:
        candidates = load_fallback_universe()
        source = "fallback_universe"
    if not candidates:
        yield "_Keine Kandidaten gefunden (Screen leer und kein Fallback verfügbar)._\n"
        return

    capped = candidates[:max_candidates]
    src_label = "Live-Screen" if source == "yfinance_screen" else "Offline-Fallback"
    yield (
        f"### Screening-Funnel\n\n- {src_label}: **{len(candidates)}** Kandidaten "
        f"→ Top **{len(capped)}** werden gegen „{parsed.nl_criterion}“ beurteilt…\n\n"
    )

    # 3. NL-Agent on each survivor (cheap prefilter skips candidates without qualifying news).
    cache: dict = {}
    matches: list[FinderMatch] = []
    for c in capped:
        news = await fetch_and_store_news(c.ticker, db, days=14)
        items = [NLItem(text=_headline_text(n), source=getattr(n, "source", None)) for n in news]
        items = [it for it in items if it.text]
        if not items:
            verdict = NLVerdict(
                matches=False, strength=0, reason="Keine aktuellen Schlagzeilen.",
                source="no_signal", mode=mode,
            )
        else:
            verdict = await evaluate_nl_target(
                parsed.nl_criterion, items, ticker="", name="", mode=mode, cache=cache
            )
        matches.append(FinderMatch(candidate=c, verdict=verdict))
        mark = "✅" if verdict.matches else "·"
        yield f"- {mark} {c.ticker}: Signifikanz {verdict.strength}/5 ({verdict.source})\n"

    # 4. Rank + render.
    yield "\n"
    yield _render_results(rank_matches(matches), parsed.nl_criterion, source)
