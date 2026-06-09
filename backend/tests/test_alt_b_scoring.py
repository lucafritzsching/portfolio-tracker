"""Integrationstests für die neue Gate-+-Stufen-Logik von score_alt_b (Alt-B Schicht 1)."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from services.screener import InsiderBuy, ScreenerStock, passes_base_filter, score_alt_b

TODAY = date(2026, 6, 9)


def _prices(closes):
    n = len(closes)
    return [SimpleNamespace(date=TODAY - timedelta(days=(n - 1 - i)), close=closes[i]) for i in range(n)]


def _news(headline, summary="", source=None):
    return SimpleNamespace(headline=headline, summary=summary, source=source,
                           published_at=datetime(2026, 6, 7), sentiment=None)


def _fund(market_cap, revenue_growth):
    return SimpleNamespace(market_cap=market_cap, revenue_growth=revenue_growth)


OVERSOLD = [100 - i * 0.5 for i in range(160)]      # ausgebombt + überverkauft -> Setup JA
UPTREND = [40 + i * 0.4 for i in range(160)]        # nahe Hoch -> Setup NEIN


def test_jazz_like_is_rejected():
    """Hochgelaufen (+Trend) + nur Routine-Präsentation (Stärke 2) -> kein Signal."""
    news = [_news("Jazz Pharmaceuticals to Present Comprehensive Data at SLEEP 2026", source="Business Wire")]
    s = score_alt_b(_fund(14.8e9, 0.19), _prices(UPTREND), news, [], ticker="JAZZ", name="Jazz Pharmaceuticals")
    assert not s.qualifies
    assert s.label == "Kein Alt-B-Signal"


def test_oversold_plus_strong_catalyst_plus_insider_is_top():
    news = [_news("XYZ Announces Positive Phase 2 Data in Lupus", source="GlobeNewswire")]
    insider = [InsiderBuy("CEO", date(2026, 6, 4), date(2026, 6, 5), 2000, 100)]  # 200k
    s = score_alt_b(_fund(2e9, 0.10), _prices(OVERSOLD), news, insider, ticker="XYZ", name="XYZ Bio")
    assert s.qualifies
    assert s.label in ("Top-Treffer", "Hohe Konviktion")
    assert s.score >= 60


def test_oversold_but_no_catalyst_is_rejected():
    s = score_alt_b(_fund(2e9, 0.10), _prices(OVERSOLD), [], [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies
    assert any("kein starker Katalysator" in line for line in s.decision_log)


def test_strong_catalyst_but_no_setup_is_rejected():
    """KYMR-Juni-/BEAM-Fall: starker Katalysator, aber schon gelaufen -> raus."""
    news = [_news("XYZ Announces Positive Phase 2 Data", source="GlobeNewswire")]
    s = score_alt_b(_fund(2e9, 0.10), _prices(UPTREND), news, [], ticker="XYZ", name="XYZ Bio")
    assert not s.qualifies
    assert any("kein Schwäche-Setup" in line for line in s.decision_log)


def test_generic_clickbait_is_not_counted():
    news = [_news("3 Unpopular Stocks We Find Risky", "mentions phase 3 data and fda", source="Motley Fool")]
    s = score_alt_b(_fund(2e9, 0.10), _prices(OVERSOLD), news, [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies  # nicht ticker-relevant -> kein Katalysator


def test_failed_trial_is_not_a_signal():
    news = [_news("ABC Bio Announces Phase 3 Trial Failed to Meet Primary Endpoint", source="GlobeNewswire")]
    s = score_alt_b(_fund(2e9, 0.10), _prices(OVERSOLD), news, [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies  # negatives Event zählt nicht


def test_commentary_recap_does_not_qualify_even_oversold():
    """Starker Inhalt, aber Kommentar-Quelle (Recap) -> auf Stärke 2 gedeckelt -> raus."""
    news = [_news("ABC Bio Is Up After Advancing Toward Accelerated Approval", source="Yahoo")]
    s = score_alt_b(_fund(2e9, 0.10), _prices(OVERSOLD), news, [], ticker="ABC", name="ABC Bio")
    assert not s.qualifies


def test_sector_downtrend_suppresses_otherwise_valid_signal():
    """Perfektes Einzelsignal, aber Biotech-Sektor im Abwärtstrend -> kein Einstieg."""
    news = [_news("XYZ Announces Positive Phase 2 Data", source="GlobeNewswire")]
    insider = [InsiderBuy("CEO", date(2026, 6, 4), date(2026, 6, 5), 2000, 100)]
    s = score_alt_b(_fund(2e9, 0.10), _prices(OVERSOLD), news, insider,
                    ticker="XYZ", name="XYZ Bio", sector_downtrend=True)
    assert not s.qualifies
    assert any("XBI" in line or "Abwärtstrend" in line for line in s.decision_log)


# ── Pre-Revenue-Fallback im Basisfilter ─────────────────────────────────────────
def _stock():
    return ScreenerStock("ABCD", "Example Bio", "NASDAQ", "Biotechnology")


def test_pre_revenue_biotech_passes_base_filter():
    # kein Umsatz (None) -> Pre-Revenue, soll NICHT ausgeschlossen werden
    assert passes_base_filter(_stock(), SimpleNamespace(market_cap=2e9, revenue_growth=None))


def test_shrinking_revenue_fails_base_filter():
    assert not passes_base_filter(_stock(), SimpleNamespace(market_cap=2e9, revenue_growth=-0.10))


def test_positive_revenue_passes_base_filter():
    assert passes_base_filter(_stock(), SimpleNamespace(market_cap=2e9, revenue_growth=0.15))
