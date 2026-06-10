"""Deterministische Ereignis-Stärke + Turnaround-Setup für den Alt-B-Screener.

Reine Funktionen, kein I/O. Ersetzt das brüchige Substring-Keyword-Matching durch:
  * Wortgrenzen-Regex  (kein "ind", das "binding" trifft)
  * Richtungs-/Negationserkennung  ("phase 3 failed" -> zählt nicht)
  * konkrete Ereignistypen statt allgemeiner Positivität
  * Turnaround-Setup aus Kursen  (ausgebombt + überverkauft)

Die Rubrik (Typ -> Stärke 1..5) lebt hier *im Code* — die Skala bleibt menschlich
kontrolliert und deterministisch. Ein LLM kann später den *Typ* liefern; die *Skala*
bleibt diese.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── Richtung: Negations-/Rückschlag-Begriffe machen ein Event "negativ" (zählt nie) ──
_NEGATIVE = re.compile(
    r"\b("
    r"fail(?:s|ed|ure|ing)?|miss(?:es|ed)?|did ?n[o']t meet|not meet(?:ing)?|"
    r"discontinu\w*|terminat\w*|halt(?:s|ed|ing)?|paus\w*|reject\w*|setback|"
    r"disappoint\w*|negative (?:data|results?|topline)|falls? short|short of|"
    r"withdraw\w*|recall\w*|lawsuit|investigation|going concern|dilut\w*|"
    r"delay\w*|cut(?:s|ting)? guidance|lower\w* guidance"
    r")\b", re.I)

# ── Stärke-Rubrik: (Stärke, Typ, Richtung, Muster). Höchste zuerst. ───────────
_RULES: list[tuple[int, str, str, list[str]]] = [
    (5, "FDA Approval", "positive", [
        r"\bfda approv\w*", r"\bapproved by the fda\b", r"\bmarketing authoriz\w*",
        r"\breceiv\w+ (?:fda )?approval\b", r"\bgrant\w+ approval\b",
    ]),
    (5, "Positive Phase-3 Daten", "positive", [
        r"\bphase 3\b.{0,70}\b(positive|met|success\w*|topline|primary endpoint)",
        r"\bpositive (?:top-?line|interim )?(?:phase ?3|pivotal)\b",
        r"\bpositive\b.{0,60}\b(?:data|results?)\b.{0,40}\b(?:phase ?3|pivotal)\b",
        r"\bpivotal\b.{0,45}\b(positive|met|success|data|results?)\b",
    ]),
    (5, "Übernahme", "positive", [
        r"\bto be acquired\b", r"\bacqui\w+ by\b", r"\bacquisition\b", r"\bmerger agreement\b",
    ]),
    (4, "FDA Fast Track / Breakthrough / Priority Review", "positive", [
        r"\bfast track\b", r"\bbreakthrough therapy\b", r"\bpriority review\b",
        r"\baccelerated approval\b", r"\borphan drug\b",
    ]),
    (4, "Positive Phase-2 Daten", "positive", [
        r"\bphase 2\b.{0,70}\b(positive|met|success\w*|topline|primary endpoint)",
        r"\bphase 1/2\b.{0,70}\b(positive|met|success\w*|topline)",
        r"\bpositive (?:top-?line|interim )?(?:phase ?2|phase ?1/2)\b",
        r"\bpositive\b.{0,60}\b(?:data|results?)\b.{0,40}\b(?:phase ?2|phase ?1/2)\b",
    ]),
    (4, "Meilensteinzahlung aus Kooperation", "positive", [
        r"\bmilestone payment\b", r"\bmilestone\b.{0,35}\bpayment\b",
        r"\b(?:earns|receives?|achieves?)\b.{0,45}\bmilestone\b",
    ]),
    (4, "Strategische Partnerschaft", "positive", [
        r"\bstrategic (?:partnership|collaboration|alliance)\b",
        r"\bcollaborat\w+ with\b", r"\bpartnership with\b",
        r"\bglobal .{0,30}collaboration\b",
    ]),
    (4, "Lizenzdeal", "positive", [
        r"\blicens\w+ (?:deal|agreement)\b", r"\bexclusive license\b",
    ]),
    (3, "Positive Phase-1 Daten", "positive", [
        r"\bphase 1\b.{0,70}\b(positive|met|success\w*|topline)",
        r"\bfirst-in-human\b.{0,70}\b(positive|data|results?)",
        r"\bpositive (?:topline |interim )?phase ?1\b",
        r"\bpositive\b.{0,60}\b(?:data|results?)\b.{0,40}\bphase ?1\b",
    ]),
    (3, "Operativer Fortschritt", "positive", [
        r"\bind\b", r"\binvestigational new drug\b", r"\braise[sd]? guidance\b",
        r"\brestructur\w*", r"\bcash runway\b",
    ]),
    (3, "Kapitalerhöhung", "neutral", [
        r"\b(?:secured|raise[sd]?|closing|priced)\b.{0,35}\b(financing|funding|offering|million)\b",
        r"\bpublic offering\b", r"\bprivate placement\b", r"\bregistered direct\b",
    ]),
    (2, "Präsentation bestehender Daten", "neutral", [
        r"\bto present\b", r"\bpresent(?:s|ed|ation|ing)\b", r"\bposter\b",
        r"\bconference\b", r"\bcomprehensive data\b", r"\binvestor (?:day|conference|update)\b",
        r"\bhighlight\w*\b", r"\bnamed to\b", r"\bappoint\w+\b",
    ]),
    (2, "Analystenmeinung", "neutral", [
        r"\banalyst\b", r"\bupgrade[sd]?\b", r"\bdowngrade[sd]?\b", r"\bprice target\b",
        r"\binitiates? coverage\b",
    ]),
    (1, "Marktkommentar", "neutral", [
        r"\bwhy .{0,30}(?:stock|shares)\b", r"\bmarket commentary\b",
        r"\bshares? (?:rise|fall|jump|drop)\b", r"\bis up\b", r"\bis down\b",
        r"\bbullish\b", r"\bbearish\b",
    ]),
    (1, "Allgemein positive Berichterstattung", "positive", [
        r"\blaunch\w*", r"\bnew product\b", r"\bexpand\w*", r"\bupside\b",
        r"\boutlook\b", r"\bgrowth\b",
    ]),
]

MIN_QUALIFYING_STRENGTH = 3

# Öffentliche Rubrik: Typ -> (Stärke, Richtung). Das LLM darf den *Typ* bestimmen,
# die Skala bleibt diese (deterministisch, testbar).
EVENT_RUBRIC: dict[str, tuple[int, str]] = {
    label: (strength, direction) for strength, label, direction, _ in _RULES
}
NO_CATALYST_TYPE = "Kein relevanter Katalysator"


@dataclass(frozen=True)
class EventClassification:
    strength: int          # 0..5  (0 = negativ oder kein Katalysator)
    type: str
    direction: str         # "positive" | "neutral" | "negative" | "none"
    capped_by_source: bool
    qualifies: bool        # positives Event mit strength >= MIN_QUALIFYING_STRENGTH


def classify_event(headline: str, summary: str = "", source: str | None = None) -> EventClassification:
    """Stärke 0..5 aus News-Text + Quelle ableiten (rein deterministisch)."""
    text = f"{headline or ''} {summary or ''}".strip()
    if not text:
        return EventClassification(0, "Kein Katalysator", "none", False, False)

    # Richtung zuerst: ein Rückschlag macht das Event negativ -> zählt nie.
    if _NEGATIVE.search(text):
        return EventClassification(0, "Negative Studiendaten", "negative", False, False)

    low = text.lower()
    strength, etype, direction = 0, "Kein relevanter Katalysator", "none"
    for s, label, event_direction, patterns in _RULES:
        if any(re.search(p, low) for p in patterns):
            strength, etype, direction = s, label, event_direction
            break

    if strength == 0:
        return EventClassification(0, etype, "none", False, False)

    # Quelle wird nicht mehr als harter Deckel genutzt: konkrete klinische,
    # regulatorische, Partnerschafts- oder Meilenstein-Events bleiben Events.
    capped = False

    return EventClassification(
        strength=strength,
        type=etype,
        direction=direction,
        capped_by_source=capped,
        qualifies=direction == "positive" and strength >= MIN_QUALIFYING_STRENGTH,
    )


def is_relevant(headline: str, summary: str, ticker: str, name: str = "") -> bool:
    """News zählt nur, wenn sie ticker-/firmenspezifisch ist (kein generischer Clickbait)."""
    text = f"{headline or ''} {summary or ''}".lower()
    if not text.strip():
        return False
    if re.search(rf"\b{re.escape(ticker.lower())}\b", text):
        return True
    first = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    for tok in first:
        if len(tok) >= 4 and tok not in ("therapeutics", "pharmaceuticals", "inc",
                                         "corp", "company", "holdings", "biosciences"):
            if re.search(rf"\b{re.escape(tok)}\b", text):
                return True
    return False


# ── Turnaround-Setup (ausgebombt + überverkauft) ────────────────────────────────
@dataclass(frozen=True)
class SetupSignal:
    is_setup: bool
    rsi: float | None
    bb_position: float | None   # 0..1 (0 = unteres Band, 1 = oberes)
    drawdown: float | None      # vom 120-Tage-Hoch, negativ
    reason: str


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        d = closes[i] - closes[i - 1]
        gains += d if d > 0 else 0.0
        losses += -d if d < 0 else 0.0
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def setup_signal(closes: list[float], dd_threshold: float = -0.15) -> SetupSignal:
    """Ausgebombt (Drawdown vom Hoch) UND überverkauft (RSI/Bollinger niedrig)?"""
    closes = [float(c) for c in closes if c is not None]
    if len(closes) < 30:
        return SetupSignal(False, None, None, None, "Zu wenig Kursdaten für Setup.")

    last = closes[-1]
    window = closes[-120:]
    peak = max(window)
    drawdown = (last - peak) / peak if peak else 0.0

    sma20 = sum(closes[-20:]) / 20
    var = sum((c - sma20) ** 2 for c in closes[-20:]) / 20
    std20 = var ** 0.5
    upper, lower = sma20 + 2 * std20, sma20 - 2 * std20
    bb_pos = (last - lower) / (upper - lower) if upper > lower else 0.5
    rsi = _rsi(closes)

    weakness = drawdown <= dd_threshold
    oversold = (rsi is not None and rsi < 40) or bb_pos < 0.25
    is_setup = weakness and oversold

    if is_setup:
        reason = f"Ausgebombt: {drawdown*100:.0f}% vom Hoch, RSI {rsi:.0f}, Bollinger {bb_pos*100:.0f}%."
    elif not weakness:
        reason = f"Keine Schwäche: nur {drawdown*100:.0f}% unter dem Hoch (schon gelaufen)."
    else:
        reason = f"Schwach, aber nicht überverkauft (RSI {rsi:.0f}, Bollinger {bb_pos*100:.0f}%)."
    return SetupSignal(is_setup, rsi, bb_pos, drawdown, reason)


def sector_regime(closes: list[float]) -> str:
    """Markt-/Sektor-Regime aus dem Biotech-Index (XBI): 'down' | 'neutral' | 'up'.

    'down' = Kurs unter der 50-Tage-Linie UND die 50-Tage fällt -> in einen solchen
    Abwärtstrend kauft man keine Turnarounds (vermeidet die sektorweiten Verlustwochen).
    """
    closes = [float(c) for c in closes if c is not None]
    if len(closes) < 55:
        return "neutral"
    last = closes[-1]
    sma50_now = sum(closes[-50:]) / 50
    sma50_prev = sum(closes[-55:-5]) / 50
    if last < sma50_now and sma50_now < sma50_prev:
        return "down"
    sma20 = sum(closes[-20:]) / 20
    if last > sma50_now and sma20 > sma50_now:
        return "up"
    return "neutral"
