"""Faithfulness gate: block LLM sentences with unbacked or wrong numbers."""
from __future__ import annotations

import re
from typing import Any

from agent.data_science import EnsembleDecision
from agent.evidence import EvidenceCatalog, render, has_unknown_evidence

REMOVED = "⚠️ _[Aussage ohne Evidence entfernt]_"

# Numbers in text (integers, decimals, percentages)
NUMBER_RE = re.compile(
    r"(?<![a-zA-Z])"
    r"(-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|-?\d+[.,]?\d*)"
    r"\s*(%|€|\$|USD|EUR)?"
)

# Label → evidence id hints for label_violations
LABEL_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bRSI\b", re.I), "rsi_14"),
    (re.compile(r"\bKGV\b|\bP/E\b|\bKurs-Gewinn", re.I), "pe_ratio"),
    (re.compile(r"\bSMA\s*50\b", re.I), "sma_50"),
    (re.compile(r"\bSMA\s*200\b", re.I), "sma_200"),
    (re.compile(r"\bMACD\b(?!.*Signal)", re.I), "macd"),
    (re.compile(r"\bKonfidenz\b", re.I), "confidence"),
    (re.compile(r"\bScore\b", re.I), "score"),
    (re.compile(r"\bBeta\b", re.I), "beta"),
]

TOLERANCE = 0.02  # relative tolerance for float match
ABS_TOLERANCE = 1.5  # absolute for RSI-like values


def _parse_num(s: str) -> float | None:
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _nums_close(a: float, b: float) -> bool:
    if abs(a - b) <= ABS_TOLERANCE:
        return True
    if b == 0:
        return abs(a) <= ABS_TOLERANCE
    return abs(a - b) / max(abs(b), 1e-9) <= TOLERANCE


def _number_backed(num: float, catalog: EvidenceCatalog) -> bool:
    for ev in catalog.numeric_values():
        if _nums_close(num, ev):
            return True
    return False


def _label_violations(sentence: str, catalog: EvidenceCatalog) -> bool:
    """True if a labeled metric in the sentence doesn't match its evidence value."""
    for pattern, ev_id in LABEL_MAP:
        m = pattern.search(sentence)
        if not m:
            continue
        entry = catalog.get(ev_id)
        if entry is None or entry.numeric is None:
            continue
        # Only check numbers near the label (avoid false positives from other metrics in same sentence)
        window = sentence[m.end() : m.end() + 40]
        for nm in NUMBER_RE.finditer(window):
            val = _parse_num(nm.group(1))
            if val is None:
                continue
            if not _nums_close(val, entry.numeric):
                return True
            break  # only the first number after the label counts
    return False


def _unbacked_numbers(sentence: str, catalog: EvidenceCatalog) -> bool:
    """True if any bare number isn't covered by the evidence catalog."""
    for m in NUMBER_RE.finditer(sentence):
        val = _parse_num(m.group(1))
        if val is None:
            continue
        # Skip small ordinals / section numbers (1., 2.)
        if abs(val) <= 3 and m.group(2) in (None, ""):
            continue
        if not _number_backed(val, catalog):
            return True
    return False


def gate_sentence(sentence: str, catalog: EvidenceCatalog) -> tuple[bool, str]:
    """Return (passed, cleaned_sentence)."""
    stripped = sentence.strip()
    if not stripped:
        return True, sentence

    rendered = render(stripped, catalog)

    if "[[?ev:" in rendered:
        return False, REMOVED

    if _label_violations(rendered, catalog):
        return False, REMOVED

    if _unbacked_numbers(rendered, catalog):
        return False, REMOVED

    return True, rendered


def apply_faithfulness_gate(text: str, catalog: EvidenceCatalog) -> str:
    """Gate each sentence; failed sentences are replaced with a warning stub."""
    # Split on sentence boundaries while keeping structure
    parts = re.split(r"(?<=[.!?])\s+|\n", text)
    out: list[str] = []
    for part in parts:
        if not part.strip():
            out.append(part)
            continue
        passed, cleaned = gate_sentence(part, catalog)
        out.append(cleaned if passed else REMOVED)
    return "\n".join(out) if "\n" in text else " ".join(out)


def check_faithfulness(
    decision: EnsembleDecision,
    explanation: str,
    catalog: EvidenceCatalog | None = None,
) -> dict[str, Any]:
    """Post-hoc check for AnalysisMetric storage."""
    notes: list[str] = []
    faithful = True

    if catalog is None:
        return {"faithful": None, "notes": "no catalog"}

    if decision.signal not in explanation.upper().replace("KAUFEN", "BUY").replace("VERKAUFEN", "SELL"):
        # Soft check: signal word should appear in some form
        sig_map = {"BUY": ("BUY", "KAUF", "NACHKAUF"), "SELL": ("SELL", "VERKAUF"), "HOLD": ("HOLD", "HALT")}
        keywords = sig_map.get(decision.signal, (decision.signal,))
        if not any(k in explanation.upper() for k in keywords):
            notes.append(f"Signal {decision.signal} nicht klar in Erklärung")
            faithful = False

    if REMOVED in explanation:
        notes.append("Ein oder mehrere Sätze durch Faithfulness-Gate entfernt")
        faithful = False

    rendered = render(explanation, catalog)
    if has_unknown_evidence(explanation) or "[[?ev:" in rendered:
        notes.append("Unbekannte Evidence-Platzhalter")
        faithful = False

    return {"faithful": faithful, "notes": "; ".join(notes) if notes else ""}
