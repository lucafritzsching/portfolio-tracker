"""Tests für die LLM-Ereignis-Klassifikation (Guardrails + Fallback, ohne echten LLM-Call)."""
import asyncio
import json

import services.event_llm as event_llm
from services.event_llm import (
    classify_event_llm,
    rubric_classification,
    validate_llm_payload,
)
from services.event_strength import NO_CATALYST_TYPE

_TEXT = "Acme Bio announces FDA approval of its lead drug for rare disease."


def _payload(**overrides):
    base = {
        "event_type": "FDA Approval",
        "direction": "positive",
        "story_de": "Die FDA hat das Hauptmedikament zugelassen.",
        "evidence_quote": "FDA approval of its lead drug",
    }
    base.update(overrides)
    return base


# ── validate_llm_payload ────────────────────────────────────────────────────────
def test_validate_accepts_good_payload():
    assert validate_llm_payload(_payload(), _TEXT) is not None


def test_validate_rejects_unknown_type():
    assert validate_llm_payload(_payload(event_type="Mondlandung"), _TEXT) is None


def test_validate_rejects_hallucinated_quote():
    assert validate_llm_payload(_payload(evidence_quote="phase 3 was a success"), _TEXT) is None


def test_validate_quote_match_ignores_case_and_whitespace():
    assert validate_llm_payload(_payload(evidence_quote="fda  Approval of its\nlead drug"), _TEXT) is not None


def test_validate_rejects_bad_direction():
    assert validate_llm_payload(_payload(direction="great"), _TEXT) is None


def test_validate_no_catalyst_needs_no_quote():
    payload = _payload(event_type=NO_CATALYST_TYPE, evidence_quote="")
    assert validate_llm_payload(payload, _TEXT) is not None


# ── rubric_classification: Skala bleibt deterministisch ────────────────────────
def test_rubric_maps_type_to_strength():
    ev = rubric_classification("FDA Approval", "positive")
    assert ev.strength == 5 and ev.direction == "positive" and ev.qualifies


def test_rubric_negative_direction_kills_event():
    ev = rubric_classification("FDA Approval", "negative")
    assert ev.strength == 0 and ev.direction == "negative" and not ev.qualifies


def test_rubric_neutral_type_never_qualifies():
    ev = rubric_classification("Kapitalerhöhung", "positive")
    assert ev.direction == "neutral" and not ev.qualifies


def test_rubric_no_catalyst():
    ev = rubric_classification(NO_CATALYST_TYPE, "positive")
    assert ev.strength == 0 and not ev.qualifies


# ── classify_event_llm: LLM-Pfad + Fallback ────────────────────────────────────
def _run(coro):
    return asyncio.run(coro)


def test_llm_path_used_when_response_valid(monkeypatch):
    async def fake_chat(messages):
        return json.dumps(_payload())

    monkeypatch.setattr(event_llm, "_ollama_chat", fake_chat)
    res = _run(classify_event_llm(_TEXT, "ACME", "Acme Bio"))
    assert res.used_llm
    assert res.classification.strength == 5
    assert res.story_de.startswith("Die FDA")
    assert res.evidence_quote


def test_fallback_on_ollama_error(monkeypatch):
    async def fake_chat(messages):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(event_llm, "_ollama_chat", fake_chat)
    res = _run(classify_event_llm(_TEXT))
    assert not res.used_llm
    assert res.classification.strength == 5  # Regex-Fallback erkennt FDA approval


def test_fallback_on_invalid_json(monkeypatch):
    async def fake_chat(messages):
        return "keine json antwort"

    monkeypatch.setattr(event_llm, "_ollama_chat", fake_chat)
    res = _run(classify_event_llm(_TEXT))
    assert not res.used_llm


def test_fallback_on_hallucinated_quote(monkeypatch):
    async def fake_chat(messages):
        return json.dumps(_payload(evidence_quote="completely made up"))

    monkeypatch.setattr(event_llm, "_ollama_chat", fake_chat)
    res = _run(classify_event_llm(_TEXT))
    assert not res.used_llm


def test_empty_text_no_llm_call(monkeypatch):
    called = False

    async def fake_chat(messages):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(event_llm, "_ollama_chat", fake_chat)
    res = _run(classify_event_llm(""))
    assert not called and res.classification.strength == 0
