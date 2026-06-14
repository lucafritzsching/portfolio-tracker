"""Integrationstests für die ursprüngliche Alt-B-Strategie.

Alt B = harter Basisfilter plus eventbasierte Turnaround-Signale:
- starkes Unternehmensereignis der letzten 7 Tage (Stärke >= 3), oder
- qualifizierter Insider-Kauf der letzten 7 Tage.
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.alt_b_signal import score_alt_b as score_alt_b_core
from services.screening_types import InsiderBuy as CoreInsiderBuy
from services.screener import InsiderBuy, ScreenerStock, passes_base_filter, score_alt_b


TODAY = date(2026, 6, 9)


def _prices(closes):
    n = len(closes)
    return [
        SimpleNamespace(date=TODAY - timedelta(days=(n - 1 - i)), close=closes[i])
        for i in range(n)
    ]


def _news(headline, summary="", source=None):
    return SimpleNamespace(
        headline=headline,
        summary=summary,
        source=source,
        published_at=datetime(2026, 6, 7),
        sentiment=None,
    )


def _fund(market_cap, revenue_growth):
    return SimpleNamespace(market_cap=market_cap, revenue_growth=revenue_growth)


PRICES = [40 + i * 0.3 for i in range(160)]
OVERSOLD = [100 - i * 0.5 for i in range(160)]
UPTREND = [40 + i * 0.4 for i in range(160)]


def _stock():
    return ScreenerStock("ABCD", "Example Bio", "NASDAQ", "Biotechnology")


def test_base_filter_pre_revenue_ok_shrinking_revenue_out():
    # ADR-13: Pre-Revenue (None) ist zulässig, nur Stagnation/Schrumpfen fällt raus.
    assert passes_base_filter(_stock(), SimpleNamespace(market_cap=2e9, revenue_growth=0.15))
    assert passes_base_filter(_stock(), SimpleNamespace(market_cap=2e9, revenue_growth=None))
    assert not passes_base_filter(_stock(), SimpleNamespace(market_cap=2e9, revenue_growth=0))
    assert not passes_base_filter(_stock(), SimpleNamespace(market_cap=2e9, revenue_growth=-0.05))
    assert not passes_base_filter(_stock(), SimpleNamespace(market_cap=16e9, revenue_growth=0.15))


def test_strong_turnaround_event_qualifies_without_setup_gate():
    news = [_news("XYZ Announces Positive Phase 2 Data in Lupus", source="GlobeNewswire")]

    score = score_alt_b(_fund(2e9, 0.10), _prices(PRICES), news, [], ticker="XYZ", name="XYZ Bio")

    assert score.qualifies
    assert score.score == 60
    assert score.label == "Watchlist Turnaround"
    assert score.turnaround_news == ["XYZ Announces Positive Phase 2 Data in Lupus"]
    assert any("Stärke 4/5" in line for line in score.decision_log)


def test_insider_buy_qualifies_even_without_news():
    insider = [InsiderBuy("CEO", date(2026, 6, 4), date(2026, 6, 5), 2000, 100)]

    score = score_alt_b(_fund(2e9, 0.10), _prices(PRICES), [], insider, ticker="XYZ", name="XYZ Bio")

    assert score.qualifies
    assert score.score == 50
    assert score.label == "Watchlist Turnaround"
    assert score.turnaround_news == []
    assert any("Qualifizierter Insider-Kauf" in line for line in score.decision_log)


def test_weak_news_does_not_qualify():
    news = [_news("XYZ to Present Comprehensive Data at ASCO", source="Business Wire")]

    score = score_alt_b(_fund(2e9, 0.10), _prices(PRICES), news, [], ticker="XYZ", name="XYZ Bio")

    assert not score.qualifies
    assert score.score == 20
    assert score.label == "Kein Alt-B-Signal"
    assert score.turnaround_news == []
    assert any("nur Stärke 2/5" in line for line in score.decision_log)


def test_failed_trial_is_not_a_positive_signal():
    news = [_news("XYZ Announces Phase 3 Trial Failed to Meet Primary Endpoint", source="GlobeNewswire")]

    score = score_alt_b(_fund(2e9, 0.10), _prices(PRICES), news, [], ticker="XYZ", name="XYZ Bio")

    assert not score.qualifies
    assert score.score == 20
    assert score.turnaround_news == []
    assert any("kein starkes turnaround-event" in line.lower() for line in score.decision_log)


def test_pre_revenue_candidate_scores_without_growth_bonus():
    news = [_news("XYZ Receives FDA Approval for Lead Drug", source="GlobeNewswire")]

    score = score_alt_b(_fund(2e9, None), _prices(PRICES), news, [], ticker="XYZ", name="XYZ Bio")

    assert score.qualifies
    assert score.score == 50  # Katalysator 50, kein Umsatz-Bonus
    assert any("Pre-Revenue" in line for line in score.decision_log)


def test_llm_event_drives_catalyst_and_story():
    from services.event_llm import LLMEvent
    from services.event_strength import EventClassification

    llm = LLMEvent(
        EventClassification(5, "FDA Approval", "positive", False, True),
        story_de="Die FDA hat das Hauptmedikament zugelassen — klarer Wendepunkt.",
        evidence_quote="FDA approval of lead drug",
        used_llm=True,
    )

    score = score_alt_b(_fund(2e9, 0.10), _prices(PRICES), [], [], ticker="XYZ", name="XYZ Bio", llm_event=llm)

    assert score.qualifies
    assert score.score == 70  # 50 Katalysator + 20 Umsatz
    assert score.used_llm
    assert score.story_de.startswith("Die FDA")
    assert score.evidence_quote == "FDA approval of lead drug"
    assert any("LLM-Klassifikation aktiv" in line for line in score.decision_log)


def test_sec_8k_event_counts_as_catalyst():
    from services.event_strength import EventClassification
    from services.sec_filings import Filing8K

    filing = Filing8K("XYZ", "2026-06-05", ["8.01"], "acc-1", "doc.htm", "Klinische Daten/FDA", True)
    ev = EventClassification(5, "FDA Approval", "positive", False, True)

    score = score_alt_b(_fund(2e9, 0.10), _prices(PRICES), [], [], ticker="XYZ", name="XYZ Bio",
                        sec_events=[(filing, ev)])

    assert score.qualifies
    assert score.score == 70
    assert any("8-K 2026-06-05" in hit for hit in score.turnaround_news)


# ── Pure Alt-B core from alt_b_signal.py ─────────────────────────────────────
def test_core_jazz_like_is_rejected():
    news = [_news("Jazz Pharmaceuticals to Present Comprehensive Data at SLEEP 2026", source="Business Wire")]
    s = score_alt_b_core(_fund(14.8e9, 0.19), _prices(UPTREND), news, [], ticker="JAZZ", name="Jazz Pharmaceuticals")
    assert not s.qualifies
    assert s.label == "Kein Alt-B-Signal"


def test_core_oversold_plus_strong_catalyst_plus_insider_is_top():
    news = [_news("XYZ Announces Positive Phase 2 Data in Lupus", source="GlobeNewswire")]
    insider = [CoreInsiderBuy("CEO", date(2026, 6, 4), date(2026, 6, 5), 2000, 100)]
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(OVERSOLD), news, insider, ticker="XYZ", name="XYZ Bio")
    assert s.qualifies
    assert s.label in ("Top-Treffer", "Hohe Konviktion")
    assert s.score >= 60


def test_core_oversold_but_no_catalyst_is_rejected():
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(OVERSOLD), [], [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies
    assert any("kein starker Katalysator" in line for line in s.decision_log)


def test_core_strong_catalyst_but_no_setup_is_rejected():
    news = [_news("XYZ Announces Positive Phase 2 Data", source="GlobeNewswire")]
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(UPTREND), news, [], ticker="XYZ", name="XYZ Bio")
    assert not s.qualifies
    assert any("kein Schwäche-Setup" in line for line in s.decision_log)


def test_core_generic_clickbait_is_not_counted():
    news = [_news("3 Unpopular Stocks We Find Risky", "mentions phase 3 data and fda", source="Motley Fool")]
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(OVERSOLD), news, [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies


def test_core_failed_trial_is_not_a_signal():
    news = [_news("ABC Bio Announces Phase 3 Trial Failed to Meet Primary Endpoint", source="GlobeNewswire")]
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(OVERSOLD), news, [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies


def test_core_commentary_recap_does_not_qualify_even_oversold():
    news = [_news("ABC Bio Is Up After Investor Conference Update", source="Yahoo")]
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(OVERSOLD), news, [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies


def test_core_sector_downtrend_suppresses_otherwise_valid_signal():
    news = [_news("XYZ Announces Positive Phase 2 Data", source="GlobeNewswire")]
    insider = [CoreInsiderBuy("CEO", date(2026, 6, 4), date(2026, 6, 5), 2000, 100)]
    s = score_alt_b_core(
        _fund(2e9, 0.10),
        _prices(OVERSOLD),
        news,
        insider,
        ticker="XYZ",
        name="XYZ Bio",
        sector_downtrend=True,
    )
    assert not s.qualifies
    assert any("XBI" in line or "Abwärtstrend" in line for line in s.decision_log)


def test_core_trace_records_gate_and_stage_steps():
    news = [_news("XYZ Announces Positive Phase 2 Data", source="GlobeNewswire")]
    insider = [CoreInsiderBuy("CEO", date(2026, 6, 4), date(2026, 6, 5), 2000, 100)]
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(OVERSOLD), news, insider, ticker="XYZ", name="XYZ Bio")
    steps = {st.step: st for st in s.trace}
    assert "Turnaround-Katalysator" in steps and "gate" in steps
    assert steps["gate"].status == "ok"
    assert steps["gate"].data["qualifies"] is True


def test_core_trace_gate_skip_when_not_qualified():
    s = score_alt_b_core(_fund(2e9, 0.10), _prices(OVERSOLD), [], [], ticker="ABC", name="ABC Bio")
    gate = next(st for st in s.trace if st.step == "gate")
    assert gate.status == "skip" and gate.data["qualifies"] is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS  {test.__name__}")
    print(f"\n{len(tests)} Tests bestanden.")
