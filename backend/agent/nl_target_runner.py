"""Free-text NL-target analysis stream for the Alt-B UI section.

Bridges the user-facing free-text feature to the ``nl_target`` engine: given a ticker and a
free-text *criterion*, fetch that ticker's recent headlines and stream a readable verdict +
decision trace. Deliberately decoupled from the biotech screener — the user names the ticker,
so there is no universe scan and no compute bottleneck.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from services.market_data import fetch_and_store_news
from services.nl_target import NLItem, NLVerdict, evaluate_nl_target


def _headline_text(news_item) -> str:
    headline = (getattr(news_item, "headline", "") or "").strip()
    summary = (getattr(news_item, "summary", "") or "").strip()
    return f"{headline}. {summary}".strip() if summary else headline


def _render_verdict(criterion: str, verdict: NLVerdict, n_items: int) -> str:
    erfuellt = "✅ Ja" if verdict.matches else "❌ Nein"
    lines = [
        "## Urteil\n",
        f"- **Erfüllt „{criterion}“:** {erfuellt}",
        f"- **Signifikanz:** {verdict.strength}/5",
    ]
    if verdict.reason:
        lines.append(f"- **Begründung:** {verdict.reason}")
    if verdict.evidence:
        lines.append(f"- **Belege ({len(verdict.evidence)}):**")
        lines.extend(f"- {h}" for h in verdict.evidence)

    src = {
        "llm": "LLM-Urteil",
        "regex_fallback": "Regex-Fallback (LLM nicht verfügbar)",
        "no_signal": "kein Signal",
    }.get(verdict.source, verdict.source)
    lines.append("\n## Nachvollziehbarkeit (Trace)\n")
    lines.append(f"- **Modus:** {verdict.mode}  ·  **Quelle:** {src}")
    lines.append(f"- **Schlagzeilen geprüft:** {n_items}  ·  deterministische Regex-Basis: {verdict.regex_strength}/5")
    if verdict.llm_strength is not None:
        lines.append(
            f"- **LLM-Rohstärke:** {verdict.llm_strength}/5 → final {verdict.strength}/5 "
            "(geklammert auf Regex-Basis ±1 — Anti-Halluzination)"
        )
    else:
        lines.append("- **LLM-Rohstärke:** – (kein LLM-Ergebnis; rein deterministischer Regex-Befund)")
    return "\n".join(lines) + "\n"


async def nl_target_stream(
    criterion: str,
    ticker: str,
    db: AsyncSession,
    mode: str = "fast",
) -> AsyncGenerator[str, None]:
    """Stream a free-text NL-target judgment for one ticker: header → load news → verdict + trace."""
    mode = "agentic" if str(mode).lower() == "agentic" else "fast"
    criterion = (criterion or "").strip()
    if not criterion:
        yield "_Kein Kriterium angegeben._\n"
        return

    yield f"## NL-Ziel-Analyse: {ticker}\n\n"
    yield f"**Kriterium:** „{criterion}“  ·  **Modus:** {mode}\n\n"

    news = await fetch_and_store_news(ticker, db, days=14)
    if not news:
        yield "_Keine aktuellen Schlagzeilen gefunden — keine NL-Beurteilung möglich._\n"
        return

    items = [NLItem(text=_headline_text(n), source=getattr(n, "source", None)) for n in news]
    items = [it for it in items if it.text]
    yield f"{len(items)} Schlagzeilen geladen, beurteile gegen das Kriterium…\n\n"

    # The news is already ticker-scoped by fetch_and_store_news, so we pass ticker="" to skip the
    # engine's ticker-relevance filter (that filter exists for broad multi-stock scans, not here).
    verdict = await evaluate_nl_target(criterion, items, ticker="", name="", mode=mode)
    yield _render_verdict(criterion, verdict, len(items))
