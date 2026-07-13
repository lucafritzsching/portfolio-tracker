"""Tests for the generalized NL judge: relevance prefilter, evidence-grounded verdict, orchestrator.

No Ollama: the LLM (fast) and chat (agentic) are injected. The key property is GROUNDING —
a positive match requires the LLM to cite a REAL headline; it can never fabricate one.
"""
import asyncio

from services.nl_target import (
    NLItem,
    _parse_llm_response,
    build_verdict,
    evaluate_nl_target,
    prefilter,
)


def _it(text, source=None):
    return NLItem(text=text, source=source)


# ── prefilter: sector-agnostic relevance only (no catalyst rubric) ────────────
def test_prefilter_keeps_nonempty_and_caps():
    survivors = prefilter([_it("AAPL beats earnings"), _it("   "), _it("AAPL launches product")])
    assert [s.text for s in survivors] == ["AAPL beats earnings", "AAPL launches product"]


def test_prefilter_relevance_filters_by_ticker_when_given():
    survivors = prefilter([_it("XYZ rises on buyout talk"), _it("Totally unrelated market wrap")],
                          ticker="XYZ", name="XYZ Inc")
    assert any("XYZ" in s.text for s in survivors)
    assert all("market wrap" not in s.text for s in survivors)


def test_prefilter_no_rubric_keeps_any_sector_headline():
    # A non-biotech, "negative-sounding" headline is NOT dropped — the criterion decides, not a rubric.
    assert len(prefilter([_it("TSLA recalls 100k cars after probe")])) == 1


# ── build_verdict: grounding, no rubric clamp ─────────────────────────────────
def test_build_verdict_no_llm_is_honest():
    v = build_verdict("x", ["h"], None)
    assert v.source == "no_llm" and v.matches is False and v.llm_strength is None


def test_build_verdict_grounded_match():
    v = build_verdict("gute News", ["h0", "h1"],
                      {"matches": True, "strength": 4, "evidence": [1], "reason": "stark"})
    assert v.matches is True and v.strength == 4 and v.evidence == ["h1"] and v.llm_strength == 4


def test_build_verdict_match_requires_real_evidence():
    # Claims a match but cites nothing real → not a match (anti-hallucination via grounding).
    assert build_verdict("x", ["h"], {"matches": True, "strength": 5, "evidence": []}).matches is False
    assert build_verdict("x", ["h0"], {"matches": True, "strength": 5, "evidence": [9, -1, "z"]}).matches is False


def test_build_verdict_below_threshold_not_match():
    v = build_verdict("x", ["h0"], {"matches": True, "strength": 2, "evidence": [0]})
    assert v.matches is False and v.strength == 2


def test_build_verdict_clamps_range_and_filters_evidence():
    v = build_verdict("x", ["h0"], {"matches": True, "strength": 9, "evidence": [0, 5]})
    assert v.strength == 5 and v.evidence == ["h0"]


# ── parser ────────────────────────────────────────────────────────────────────
def test_parse_llm_response_extracts_json():
    obj = _parse_llm_response('noise {"matches": true, "strength": 4, "evidence": [0]} tail')
    assert obj["matches"] is True and obj["strength"] == 4


def test_parse_llm_response_rejects_junk():
    assert _parse_llm_response("no json") is None
    assert _parse_llm_response('{"strength": 3}') is None   # missing "matches"
    assert _parse_llm_response("") is None


# ── evaluate_nl_target orchestration (no Ollama) ──────────────────────────────
def test_evaluate_no_signal_when_no_survivors():
    async def fake_llm(criterion, items):
        raise AssertionError("LLM must not run without survivors")
    v = asyncio.run(evaluate_nl_target("x", [_it("   ")], llm_fn=fake_llm, cache={}))
    assert v.source == "no_signal" and v.matches is False


def test_evaluate_no_llm_returns_honest_verdict():
    async def fake_llm(criterion, items):
        return None
    v = asyncio.run(evaluate_nl_target("x", [_it("AAPL beats earnings")], llm_fn=fake_llm, cache={}))
    assert v.source == "no_llm" and v.matches is False


def test_evaluate_uses_llm_and_caches():
    calls = {"n": 0}

    async def fake_llm(criterion, items):
        calls["n"] += 1
        return {"matches": True, "strength": 4, "evidence": [0], "reason": "ok"}

    items = [_it("AAPL beats earnings and raises guidance")]
    cache: dict = {}
    v1 = asyncio.run(evaluate_nl_target("gute News", items, llm_fn=fake_llm, cache=cache))
    v2 = asyncio.run(evaluate_nl_target("gute News", items, llm_fn=fake_llm, cache=cache))
    assert v1.matches is True and v1.evidence == ["AAPL beats earnings and raises guidance"]
    assert calls["n"] == 1 and v2 is v1


# ── agentic (self-contained tool-loop, no Ollama) ─────────────────────────────
def test_inspect_headline_returns_text_no_rubric():
    from services.nl_target import _inspect_headline
    out = _inspect_headline(0, [_it("AAPL beats earnings", "Reuters")])
    assert "AAPL beats earnings" in out and "regex" not in out
    assert _inspect_headline(9, []).startswith("Index")


def test_agentic_inspects_then_verdicts():
    turns = {"n": 0}

    async def fake_chat(messages, tools):
        turns["n"] += 1
        if turns["n"] == 1:
            return {"content": "", "tool_calls": [{"function": {"name": "inspect_headline", "arguments": {"index": 0}}}]}
        return {"content": '{"matches": true, "strength": 4, "evidence": [0], "reason": "ok"}', "tool_calls": []}

    v = asyncio.run(evaluate_nl_target("gute News", [_it("AAPL beats earnings")],
                                       mode="agentic", chat_fn=fake_chat, cache={}))
    assert v.mode == "agentic" and v.matches is True and turns["n"] == 2


def test_agentic_no_verdict_json_is_honest():
    async def fake_chat(messages, tools):
        return {"content": "denke noch nach…", "tool_calls": []}
    v = asyncio.run(evaluate_nl_target("x", [_it("AAPL beats earnings")],
                                       mode="agentic", chat_fn=fake_chat, cache={}))
    assert v.source == "no_llm" and v.mode == "agentic"
