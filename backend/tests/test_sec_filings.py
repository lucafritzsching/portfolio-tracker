"""Tests für die reinen SEC-8-K-Helfer (Alt-B Schicht 2)."""
from services.event_strength import EventClassification
from services.sec_filings import (
    Filing8K,
    classify_8k_type,
    is_catalyst_candidate,
    parse_items,
    parse_recent_signals,
    strip_html,
    strongest_catalyst,
)


def _filing(date="2025-06-02"):
    return Filing8K("ABC", date, ["8.01"], "x-1", "d.htm", "Sonstiges", True)


def _ev(strength, direction="positive"):
    return EventClassification(strength, "t", direction, False, strength >= 3)


def test_parse_items():
    assert parse_items("7.01,8.01,9.01") == ["7.01", "8.01", "9.01"]
    assert parse_items("") == []
    assert parse_items(None) == []


def test_classify_type():
    assert classify_8k_type(["1.01", "9.01"]) == "Partnerschaft/Vertrag"
    assert "klinische" in classify_8k_type(["8.01", "9.01"])
    assert classify_8k_type(["2.02"]) == "Quartalszahlen"
    assert classify_8k_type(["5.02"]) == "Management-Wechsel"
    assert classify_8k_type(["9.01"]) == "Sonstiges"


def test_catalyst_candidate():
    assert is_catalyst_candidate(["8.01", "9.01"])      # sonstiges Wesentliches
    assert is_catalyst_candidate(["1.01"])               # Partnerschaft
    assert is_catalyst_candidate(["7.01", "9.01"])       # Regulation FD
    assert not is_catalyst_candidate(["5.02"])           # nur Management
    assert not is_catalyst_candidate(["2.02", "9.01"])   # nur Zahlen
    assert not is_catalyst_candidate(["9.01"])           # nur Exhibits


def test_strip_html():
    assert strip_html("<p>Phase 3 <b>positive</b></p>") == "Phase 3 positive"
    assert strip_html("") == ""


# ── strongest_catalyst (Stärke-Filter für den Backtest) ─────────────────────────
def test_strongest_catalyst_empty():
    assert strongest_catalyst([]) is None


def test_strongest_catalyst_picks_highest_strong():
    cats = [(_filing(), _ev(3)), (_filing(), _ev(5)), (_filing(), _ev(4))]
    res = strongest_catalyst(cats, min_strength=4)
    assert res is not None and res[1].strength == 5


def test_strongest_catalyst_below_threshold_is_none():
    # nur Stärke 3 vorhanden, Schwelle 4 -> kein starker Katalysator
    assert strongest_catalyst([(_filing(), _ev(3))], min_strength=4) is None


def test_strongest_catalyst_ignores_negative():
    assert strongest_catalyst([(_filing(), _ev(5, "negative"))], min_strength=4) is None


# ── parse_recent_signals (Vorprüfung: 8-K-Katalysator + Form 4 aus EINEM Call) ──
def _recent(forms, dates, items):
    return {"form": forms, "filingDate": dates, "items": items}


def test_recent_signals_catalyst_8k_and_form4():
    recent = _recent(
        ["8-K", "4", "10-Q"],
        ["2025-06-02", "2025-06-03", "2025-06-01"],
        ["8.01,9.01", "", ""],
    )
    assert parse_recent_signals(recent, "2025-06-01", "2025-06-07") == (True, True)


def test_recent_signals_routine_8k_is_no_catalyst():
    recent = _recent(["8-K"], ["2025-06-02"], ["2.02,9.01"])  # nur Quartalszahlen
    assert parse_recent_signals(recent, "2025-06-01", "2025-06-07") == (False, False)


def test_recent_signals_outside_window():
    recent = _recent(["8-K", "4"], ["2025-05-01", "2025-05-02"], ["8.01", ""])
    assert parse_recent_signals(recent, "2025-06-01", "2025-06-07") == (False, False)


def test_recent_signals_form4_only():
    recent = _recent(["4"], ["2025-06-04"], [""])
    assert parse_recent_signals(recent, "2025-06-01", "2025-06-07") == (False, True)


def test_recent_signals_empty():
    assert parse_recent_signals({}, "2025-06-01", "2025-06-07") == (False, False)
