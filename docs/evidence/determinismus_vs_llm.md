# Determinismus vs. LLM — Evidenz-Hub (für die Demo)

> Beantwortet die Forschungsfrage *„deterministisch vs. (geführtes/pures) LLM — was liefert bessere
> Ergebnisse?"* mit **gemessenen Zahlen**, nicht mit Bauchgefühl. Alle Zahlen sind reproduzierbar.
> ⚠️ Genauigkeits-/Latenzzahlen stammen aus dem 36-Fälle-Lauf **vor dem `think:false`-Fix** (Re-Run offen).

## Drei Achsen

### A) Tool-Calling-Agent vs. ein einzelner LLM-Call
| Modus | Trefferquote |
|---|---|
| `fast` (1 LLM-Call) | 14/18 = **78 %** |
| `agentic` (Tool-Loop, `inspect_headline`) | 16/18 = **89 %** |

Der agentische Pfad (LLM darf Schlagzeilen via Tool prüfen) liegt **+11 Pp** vorn. Reproduzierbar:
[`axes_analysis.py`](axes_analysis.py) (A) · Audit: [`refactor_nl_verify.py`](refactor_nl_verify.py).

### B) Geführt (regex-Clamp) vs. pures LLM (ohne Clamp) — 32 LLM-Läufe
| Variante | Trefferquote | False-Positives |
|---|---|---|
| **geführt** (final, Clamp regex ±1) | 26/32 = **81 %** | **0** |
| pur (ohne Clamp, Proxy `llm_strength≥3`) | 25/32 = 78 % | 2 |

Der deterministische Clamp bringt **+3 Pp** und **eliminiert 2 False-Positives** (das LLM wollte einen
Katalysator behaupten, den die Regex-Basis nicht stützt). **Ehrliche Kehrseite:** in **1** Fall (`05-fast`)
unterdrückte der Clamp ein *korrektes* LLM-Urteil, weil die (biotech-getunte) Regex-Rubrik das Signal nicht
erkannte — der Guard ist nicht gratis. Reproduzierbar: [`axes_analysis.py`](axes_analysis.py) (B).

**Halluzinations-Guard:** 3 Überhöhungsversuche (regex 0 ∧ LLM-Roh ≥ 3), **0 kamen durch** → 0 Halluzinationen.

### C) `think:false` vs. `think:true` (qwen3)
Latenz **4–10×** höher mit Thinking; **Kern-Urteil identisch**; Divergenz nur in Belegauswahl + Sprache;
**kein** Parsing-Problem (separates `thinking`-Feld). Details + Messung: [`think_mode_findings.md`](think_mode_findings.md),
reproduzierbar via [`think_mode_probe.py`](think_mode_probe.py).

## Einordnung auf der Determinismus↔LLM-Skala
```
 rein deterministisch ───────────────────────────────────────────► reines LLM
 │                       │                      │                    │
 Alt A                   Alt B agentic          Alt B fast           „pures LLM" (ohne Guard)
 (Ensemble entscheidet,  (LLM+Tools+regex,      (LLM+regex-Clamp,    (kein Clamp/Prefilter)
  LLM erklärt, Evidence)  89 %)                  81 % geführt)        78 %, +2 FP
```
**Fazit für die Demo:** Die deterministischen Leitplanken (Prefilter, Clamp, Prompt-Constraint, T=0) tragen
die Qualität messbar mit — „mehr LLM" allein (mehr Thinking, kein Guard) bringt **nicht** automatisch
bessere/strukturiertere Ergebnisse, kostet aber Latenz und erzeugt False-Positives.
