"""Unit tests for evidence rendering and faithfulness gate."""
from agent.evidence import build_evidence_catalog, render, EvidenceCatalog, EvidenceEntry
from agent.data_science import EnsembleDecision
from eval.faithfulness import gate_sentence, apply_faithfulness_gate


def _minimal_decision() -> EnsembleDecision:
    return EnsembleDecision(
        signal="HOLD",
        score=0.1,
        confidence=0.55,
        components={"technical": {"value": 0.2, "weight": 0.3, "contribution": 0.06}},
        rationale=["Test"],
        technicals={"rsi_14": 55.0, "current_price": 100.0},
    )


def test_render_replaces_placeholder():
    catalog = build_evidence_catalog("AAPL", _minimal_decision(), {
        "technicals": {"rsi_14": 55.0, "current_price": 100.0},
        "price_points": 200,
        "has_price_data": True,
    })
    out = render("RSI ist {{ev:rsi_14}}.", catalog)
    assert "55" in out
    assert "{{ev:" not in out


def test_render_unknown_id():
    catalog = EvidenceCatalog(ticker="X", entries={})
    out = render("Wert {{ev:missing}}.", catalog)
    assert "[[?ev:missing]]" in out


def test_gate_rejects_unbacked_number():
    catalog = build_evidence_catalog("AAPL", _minimal_decision(), {
        "technicals": {"rsi_14": 55.0},
        "price_points": 200,
        "has_price_data": True,
    })
    passed, _ = gate_sentence("Der Kurs steht bei 999.99 USD.", catalog)
    assert passed is False


def test_gate_accepts_evidence_number():
    catalog = build_evidence_catalog("AAPL", _minimal_decision(), {
        "technicals": {"rsi_14": 55.0, "current_price": 100.0},
        "price_points": 200,
        "has_price_data": True,
    })
    passed, cleaned = gate_sentence("RSI {{ev:rsi_14}} und Kurs {{ev:current_price}}.", catalog)
    assert passed is True
    assert "55" in cleaned


def test_apply_gate_removes_bad_sentence():
    catalog = build_evidence_catalog("AAPL", _minimal_decision(), {
        "technicals": {"rsi_14": 55.0},
        "price_points": 200,
        "has_price_data": True,
    })
    text = "Gut. Der Kurs ist 5000. Fazit."
    gated = apply_faithfulness_gate(text, catalog)
    assert "5000" not in gated
    assert "Aussage ohne Evidence" in gated
