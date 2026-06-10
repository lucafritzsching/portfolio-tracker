"""Alt-B Backtest-Harness (Phase 3): misst Alpha (Exzess vs. XBI) je Strategie-Säule.

Reine Rechenteile (Alpha-Aggregation, Gruppen-Zuordnung) sind unit-getestet; das Daten-
Sammeln (Preise, 8-K, Insider) ist I/O und läuft im Runner-Skript.

Auswertungsregel (VORHER fixiert, gegen Overfitting):
  Eine Säule hat „Edge", wenn ihr **Median-Alpha klar > 0** ist (z. B. > +2 pp) UND die
  **Trefferquote > 50 %**, bei **N >= 30**. Sonst: kein belastbarer Edge.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

MIN_STRONG = 4          # Stärke-Schwelle für "starker" Katalysator
MIN_QUALIFY = 3         # Stärke-Schwelle für "Katalysator zählt überhaupt"


@dataclass
class BacktestEvent:
    ticker: str
    date: str
    setup: bool                 # ausgebombt + überverkauft am Event-Tag
    insider: bool               # qualifizierter Insider-Kauf in den 7 Tagen davor
    catalyst_strength: int      # 0 = kein Katalysator (Baseline), sonst 1..5
    alpha: float                # Forward-30T-Rendite − XBI-Rendite (in %)


def pct(start: float, end: float) -> float:
    """Prozentuale Veränderung start -> end."""
    return (end - start) / start * 100 if start else 0.0


def summarize(alphas: list[float]) -> dict:
    """N, Median, Mittel, Trefferquote (% > 0) einer Alpha-Verteilung."""
    if not alphas:
        return {"n": 0, "median": None, "mean": None, "win_rate": None}
    return {
        "n": len(alphas),
        "median": round(statistics.median(alphas), 1),
        "mean": round(sum(alphas) / len(alphas), 1),
        "win_rate": round(sum(1 for a in alphas if a > 0) / len(alphas) * 100),
    }


def group_alphas(events: list[BacktestEvent]) -> dict[str, list[float]]:
    """Events nach Alt-B-Säulen + Kombinationen in Alpha-Listen einsortieren (pure)."""
    cat3 = [e for e in events if e.catalyst_strength >= MIN_QUALIFY]
    cat4 = [e for e in events if e.catalyst_strength >= MIN_STRONG]
    return {
        "Baseline (Zufallseinstieg)":      [e.alpha for e in events if e.catalyst_strength == 0 and not e.setup],
        "Katalysator >= 3":                 [e.alpha for e in cat3],
        "Katalysator >= 4 (stark)":         [e.alpha for e in cat4],
        "Setup allein":                     [e.alpha for e in events if e.setup and e.catalyst_strength == 0],
        "Setup + Katalysator >= 3":         [e.alpha for e in cat3 if e.setup],
        "Setup + Katalysator >= 4":         [e.alpha for e in cat4 if e.setup],
        "Katalysator + Insider":            [e.alpha for e in cat3 if e.insider],
        "VOLL Alt-B (Setup+Kat+Insider)":   [e.alpha for e in cat3 if e.setup and e.insider],
    }


def has_edge(stats: dict, min_median: float = 2.0, min_n: int = 30) -> bool:
    """Vorab fixierte Edge-Regel: Median-Alpha > Schwelle, Trefferquote > 50 %, N >= min_n."""
    return (
        stats["n"] >= min_n
        and stats["median"] is not None
        and stats["median"] > min_median
        and stats["win_rate"] is not None
        and stats["win_rate"] > 50
    )
