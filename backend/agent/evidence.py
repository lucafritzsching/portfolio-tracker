"""Evidence catalog: canonical numbers for LLM explanations (anti-hallucination)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.data_science import EnsembleDecision

EV_PLACEHOLDER = re.compile(r"\{\{ev:([a-zA-Z0-9_]+)\}\}")
UNKNOWN_EV = re.compile(r"\[\[\?ev:[^\]]+\]\]")


@dataclass
class EvidenceEntry:
    id: str
    label: str
    value: float | int | str
    numeric: float | None = None  # for faithfulness matching


@dataclass
class EvidenceCatalog:
    ticker: str
    entries: dict[str, EvidenceEntry] = field(default_factory=dict)

    def get(self, ev_id: str) -> EvidenceEntry | None:
        return self.entries.get(ev_id)

    def numeric_values(self) -> list[float]:
        out: list[float] = []
        for e in self.entries.values():
            if e.numeric is not None:
                out.append(e.numeric)
        return out


def _add_num(catalog: EvidenceCatalog, ev_id: str, label: str, value: Any) -> None:
    if value is None:
        return
    try:
        num = float(value)
    except (TypeError, ValueError):
        catalog.entries[ev_id] = EvidenceEntry(id=ev_id, label=label, value=str(value), numeric=None)
        return
    catalog.entries[ev_id] = EvidenceEntry(
        id=ev_id, label=label, value=_fmt_num(num), numeric=num
    )


def _fmt_num(n: float) -> str:
    if abs(n) >= 100:
        return f"{n:.2f}"
    if abs(n) >= 1:
        return f"{n:.2f}"
    return f"{n:.3f}"


def build_evidence_catalog(
    ticker: str,
    decision: EnsembleDecision,
    context: dict,
) -> EvidenceCatalog:
    """Build stable evidence IDs from pipeline output only."""
    catalog = EvidenceCatalog(ticker=ticker.upper())

    _add_num(catalog, "score", "Ensemble-Score", decision.score)
    _add_num(catalog, "confidence", "Konfidenz", decision.confidence)
    catalog.entries["signal"] = EvidenceEntry(
        id="signal", label="Empfehlung", value=decision.signal, numeric=None
    )

    for name, comp in decision.components.items():
        _add_num(catalog, f"comp_{name}", f"Komponente {name}", comp.get("value"))
        if comp.get("contribution") is not None:
            _add_num(catalog, f"contrib_{name}", f"Beitrag {name}", comp["contribution"])

    tech = context.get("technicals") or {}
    _add_num(catalog, "current_price", "Aktueller Kurs", tech.get("current_price"))
    _add_num(catalog, "sma_50", "SMA 50", tech.get("sma_50"))
    _add_num(catalog, "sma_200", "SMA 200", tech.get("sma_200"))
    _add_num(catalog, "bollinger_upper", "Bollinger oben", tech.get("bollinger_upper"))
    _add_num(catalog, "bollinger_lower", "Bollinger unten", tech.get("bollinger_lower"))
    _add_num(catalog, "arima_forecast_7d", "ARIMA 7T", tech.get("arima_forecast_7d"))
    _add_num(catalog, "arima_forecast_30d", "ARIMA 30T", tech.get("arima_forecast_30d"))
    _add_num(catalog, "rsi_14", "RSI 14", tech.get("rsi_14"))
    _add_num(catalog, "macd", "MACD", tech.get("macd"))
    _add_num(catalog, "macd_signal", "MACD Signal", tech.get("macd_signal_line"))

    fund = context.get("fundamentals") or {}
    _add_num(catalog, "pe_ratio", "KGV", fund.get("pe_ratio"))
    _add_num(catalog, "revenue_growth", "Umsatzwachstum", fund.get("revenue_growth"))
    _add_num(catalog, "market_cap", "Marktkapitalisierung", fund.get("market_cap"))
    _add_num(catalog, "fifty_two_week_high", "52W Hoch", fund.get("fifty_two_week_high"))
    _add_num(catalog, "fifty_two_week_low", "52W Tief", fund.get("fifty_two_week_low"))
    _add_num(catalog, "beta", "Beta", fund.get("beta"))

    _add_num(catalog, "news_sentiment", "News-Sentiment", context.get("news_sentiment"))

    port = context.get("portfolio") or {}
    _add_num(catalog, "avg_buy_price", "Ø Kaufpreis", port.get("avg_buy_price"))
    _add_num(catalog, "unrealized_pnl_pct", "Unrealisierter Gewinn %", port.get("unrealized_pnl_pct"))
    _add_num(catalog, "portfolio_weight", "Portfoliogewicht %", port.get("portfolio_weight"))

    _add_num(catalog, "price_points", "Datenpunkte", context.get("price_points"))

    return catalog


def format_catalog_for_prompt(catalog: EvidenceCatalog) -> str:
    lines = []
    for ev_id, entry in sorted(catalog.entries.items()):
        lines.append(f"- {ev_id}: {entry.label} = {entry.value}")
    return "\n".join(lines)


def render(text: str, catalog: EvidenceCatalog) -> str:
    """Replace {{ev:id}} with canonical values; unknown IDs become [[?ev:id]]."""

    def _repl(m: re.Match) -> str:
        ev_id = m.group(1)
        entry = catalog.get(ev_id)
        if entry is None:
            return f"[[?ev:{ev_id}]]"
        return str(entry.value)

    return EV_PLACEHOLDER.sub(_repl, text)


def has_unknown_evidence(text: str) -> bool:
    return bool(UNKNOWN_EV.search(text) or EV_PLACEHOLDER.search(render(text, EvidenceCatalog("", {}))))
