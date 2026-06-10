"""Tests for the NL-target evaluator (prefilter, verdict combination, LLM orchestrator)."""
import asyncio

from services.nl_target import (
    NLItem,
    _parse_llm_response,
    combine_verdict,
    evaluate_nl_target,
    prefilter,
)


def _it(text, source=None):
    return NLItem(text=text, source=source)


def test_prefilter_keeps_relevant_drops_negative_and_irrelevant():
    items = [
        _it("XYZ Announces Positive Phase 2 Data in Lupus", "GlobeNewswire"),  # relevant + strong
        _it("3 Stocks We Find Risky This Week", "Motley Fool"),                  # irrelevant
        _it("XYZ Phase 3 Trial Failed to Meet Primary Endpoint", "GlobeNewswire"),  # negative
    ]
    survivors, regex_strength, qualifying = prefilter(items, ticker="XYZ", name="XYZ Bio")
    texts = [s.text for s in survivors]
    assert any("Phase 2" in t for t in texts)
    assert all("Failed" not in t for t in texts)        # negative dropped
    assert all("3 Stocks" not in t for t in texts)       # irrelevant dropped
    assert regex_strength >= 3 and qualifying


def test_prefilter_empty_when_nothing_relevant():
    survivors, regex_strength, qualifying = prefilter([_it("Generic market wrap")], ticker="XYZ", name="XYZ Bio")
    assert survivors == [] and regex_strength == 0 and qualifying == []


def test_combine_fallback_equals_regex_when_llm_none():
    v = combine_verdict("turnaround", regex_strength=4, qualifying_headlines=["h"], survivor_texts=["h"], llm_result=None)
    assert v.source == "regex_fallback" and v.strength == 4 and v.matches is True
    assert v.llm_strength is None


def test_combine_fallback_below_threshold_does_not_match():
    v = combine_verdict("turnaround", regex_strength=2, qualifying_headlines=[], survivor_texts=["h"], llm_result=None)
    assert v.source == "regex_fallback" and v.matches is False


def test_combine_clamps_llm_up_to_regex_plus_one():
    # regex baseline 3, LLM claims 5 -> clamp to 4, evidence index resolved
    v = combine_verdict("c", 3, ["q"], ["h0", "h1"],
                        {"matches": True, "strength": 5, "evidence": [0], "reason": "stark"})
    assert v.strength == 4 and v.matches is True and v.evidence == ["h0"] and v.llm_strength == 5


def test_combine_regex_guardrail_blocks_fabrication():
    # regex found nothing (0); LLM claims a strong match -> clamped to <=1 -> matches False
    v = combine_verdict("c", 0, [], ["h0"], {"matches": True, "strength": 5, "evidence": [0], "reason": "x"})
    assert v.strength <= 1 and v.matches is False


def test_combine_filters_invalid_evidence_indices():
    v = combine_verdict("c", 3, ["q"], ["h0"], {"matches": True, "strength": 3, "evidence": [0, 5, -1, "x"], "reason": "r"})
    assert v.evidence == ["h0"]


# ── LLM layer (parser + async orchestrator, no Ollama needed) ────────────────────
def test_parse_llm_response_extracts_json():
    obj = _parse_llm_response('noise {"matches": true, "strength": 4, "evidence": [0]} tail')
    assert obj["matches"] is True and obj["strength"] == 4


def test_parse_llm_response_rejects_junk():
    assert _parse_llm_response("no json here") is None
    assert _parse_llm_response('{"strength": 3}') is None   # missing "matches"
    assert _parse_llm_response("") is None


def test_evaluate_falls_back_when_llm_returns_none():
    async def fake_llm(criterion, items):
        return None
    items = [_it("XYZ Announces Positive Phase 2 Data", "GlobeNewswire")]
    v = asyncio.run(evaluate_nl_target("turnaround", items, ticker="XYZ", name="XYZ Bio",
                                       llm_fn=fake_llm, cache={}))
    assert v.source == "regex_fallback" and v.matches is True


def test_evaluate_no_signal_skips_llm_when_no_relevant_news():
    async def fake_llm(criterion, items):
        raise AssertionError("LLM must not be called when there are no survivors")
    v = asyncio.run(evaluate_nl_target("turnaround", [_it("Generic market wrap")],
                                       ticker="XYZ", name="XYZ Bio", llm_fn=fake_llm, cache={}))
    assert v.source == "no_signal" and v.matches is False


def test_evaluate_uses_llm_and_caches_success():
    calls = {"n": 0}

    async def fake_llm(criterion, items):
        calls["n"] += 1
        return {"matches": True, "strength": 5, "evidence": [0], "reason": "stark"}

    items = [_it("XYZ Announces Positive Phase 2 Data", "GlobeNewswire")]
    cache: dict = {}
    v1 = asyncio.run(evaluate_nl_target("turnaround", items, ticker="XYZ", name="XYZ Bio",
                                        llm_fn=fake_llm, cache=cache))
    v2 = asyncio.run(evaluate_nl_target("turnaround", items, ticker="XYZ", name="XYZ Bio",
                                        llm_fn=fake_llm, cache=cache))
    assert v1.matches is True and 3 <= v1.strength <= 5
    assert v1.evidence == ["XYZ Announces Positive Phase 2 Data"]
    assert calls["n"] == 1 and v2 is v1   # second call served from cache
