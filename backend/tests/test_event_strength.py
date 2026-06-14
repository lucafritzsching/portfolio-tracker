"""Tests für die deterministische Ereignis-Stärke + Setup-Logik (Alt-B Schicht 1)."""
from services.event_strength import classify_event, is_relevant, sector_regime, setup_signal


# ── Stärke-Rubrik ───────────────────────────────────────────────────────────────
def test_fda_approval_is_strength_5():
    ev = classify_event("Company Receives FDA Approval for Lead Drug", source="GlobeNewswire")
    assert ev.strength == 5 and ev.qualifies


def test_positive_phase1_first_in_human_qualifies():
    ev = classify_event(
        "Kymera Announces Positive First-in-Human Results from Phase 1 Trial of KT-621",
        source="GlobeNewswire",
    )
    assert ev.strength >= 3 and ev.direction == "positive" and ev.qualifies


def test_routine_presentation_is_weak():
    ev = classify_event(
        "Jazz Pharmaceuticals to Present Comprehensive Data at SLEEP 2026",
        source="Business Wire",
    )
    assert ev.strength == 2 and not ev.qualifies


def test_positive_phase2_event_is_not_downgraded_by_presentation_wording():
    ev = classify_event(
        "Biotech Announces Positive Phase 2 Data and Will Present Results at ASCO",
        source="GlobeNewswire",
    )
    assert ev.type == "Positive Phase-2 Daten"
    assert ev.strength == 4
    assert ev.direction == "positive"
    assert ev.qualifies


def test_positive_phase2_comprehensive_data_beats_generic_presentation_rule():
    ev = classify_event(
        "Biotech Announces Positive Comprehensive Data from Phase 2 Trial in Rare Disease",
        source="GlobeNewswire",
    )
    assert ev.type == "Positive Phase-2 Daten"
    assert ev.strength == 4
    assert ev.qualifies


def test_failed_trial_is_negative_and_zero():
    ev = classify_event("Company Announces Phase 3 Trial Failed to Meet Primary Endpoint",
                        source="GlobeNewswire")
    assert ev.strength == 0 and ev.direction == "negative" and not ev.qualifies


def test_no_substring_bug_ind_in_binding():
    # "binding" darf NICHT als IND (Stärke 3) klassifiziert werden.
    ev = classify_event("Study shows improved binding affinity of the molecule", source="Zacks")
    assert ev.strength == 0


def test_partnership_is_strength_4():
    ev = classify_event("Biotech Announces Strategic Collaboration with Pfizer",
                        source="PR Newswire")
    assert ev.strength == 4 and ev.qualifies


def test_commentary_source_does_not_cap_concrete_clinical_event():
    pr = classify_event("Positive Phase 2 data reported", source="GlobeNewswire")
    media = classify_event("Positive Phase 2 data reported", source="Yahoo")
    assert pr.strength == 4 and not pr.capped_by_source
    assert media.strength == 4 and not media.capped_by_source and media.qualifies


def test_milestone_payment_is_relevant_even_from_media_source():
    ev = classify_event(
        "Atrium Therapeutics Earns $15 Million Milestone Payment from Bristol Myers Squibb Under Global Cardiovascular Collaboration",
        source="Yahoo",
    )
    assert ev.type == "Meilensteinzahlung aus Kooperation"
    assert ev.strength == 4
    assert ev.direction == "positive"
    assert ev.qualifies


def test_analyst_opinion_stays_weak():
    ev = classify_event("Analyst Upgrades Biotech and Raises Price Target", source="MarketWatch")
    assert ev.type == "Analystenmeinung"
    assert ev.strength == 2
    assert not ev.qualifies


def test_capital_raise_is_concrete_but_not_positive_turnaround_candidate():
    ev = classify_event("Biotech Prices $75 Million Public Offering", source="GlobeNewswire")
    assert ev.type == "Kapitalerhöhung"
    assert ev.strength == 3
    assert ev.direction == "neutral"
    assert not ev.qualifies


# ── Relevanz ────────────────────────────────────────────────────────────────────
def test_generic_clickbait_not_relevant():
    assert not is_relevant("3 Unpopular Stocks We Find Risky", "", "CRSP", "CRISPR Therapeutics")


def test_company_name_makes_relevant():
    assert is_relevant("CRISPR Therapeutics Announces New Data", "", "CRSP", "CRISPR Therapeutics")


def test_ticker_makes_relevant():
    assert is_relevant("Why CRSP could double", "", "CRSP", "CRISPR Therapeutics")


# ── Turnaround-Setup ────────────────────────────────────────────────────────────
def test_oversold_drawdown_is_setup():
    closes = [100 - i * 0.5 for i in range(160)]  # stetig fallend -> ausgebombt + überverkauft
    s = setup_signal(closes)
    assert s.is_setup and s.drawdown < -0.15


def test_uptrend_is_not_setup():
    closes = [40 + i * 0.5 for i in range(160)]   # stetig steigend -> nahe Hoch
    s = setup_signal(closes)
    assert not s.is_setup


def test_extended_after_rally_is_not_setup():
    # erst runter, dann +96% hoch (KYMR Juni / BEAM): nicht mehr ausgebombt
    closes = [50 - i for i in range(28)] + [22 + i * 2 for i in range(132)]
    s = setup_signal(closes)
    assert not s.is_setup


# ── Sektor-Regime (XBI) ─────────────────────────────────────────────────────────
def test_sector_regime_down():
    closes = [100 - i * 0.3 for i in range(80)]   # fallend
    assert sector_regime(closes) == "down"


def test_sector_regime_up():
    closes = [40 + i * 0.3 for i in range(80)]     # steigend
    assert sector_regime(closes) == "up"


def test_sector_regime_too_short_is_neutral():
    assert sector_regime([100, 101, 99]) == "neutral"
