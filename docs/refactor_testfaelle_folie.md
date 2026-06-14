# Präsentationsfolie — Experiment-Auswertung NL-Ziel-Agent

> 6 repräsentative Testfälle (aus 18) · Modell `qwen3:14b` · Kriterium „aktuelle Turnaround-Story".
> Alle Werte 1:1 aus [refactor_nl_validation_raw.json](evidence/refactor_nl_validation_raw.json) —
> keine erfundenen Beispiele. „Fast"/„Agentic" = Urteil des Modells (Match Ja/Nein).

| Kategorie | Headline | Erwartung | Fast | Agentic | Korrekt? |
|---|---|:--:|:--:|:--:|:--:|
| Klare positive News (FDA-Zulassung) | „Beta Pharma Receives FDA Approval for Lead Drug in Rare Disease" | Match | **Nein** | **Ja** | fast ✗ · agentic ✓ |
| Partnership / Collaboration | „CytomX Expands Collaboration and Licensing Agreement With Regeneron" | Match | **Nein** | **Ja** | fast ✗ · agentic ✓ |
| Analystenmeldung | „RBC Capital Maintains Outperform on Alkermes, Raises Price Target to $56" | kein Match | Nein | Nein | beide ✓ |
| Konferenzmeldung | „AbCellera Biologics Presents at Jefferies Global Healthcare Conference 2026" | kein Match | Nein | Nein | beide ✓ |
| Negative News | „Gamma Therapeutics Announces Phase 3 Trial Failed to Meet Primary Endpoint" | kein Match | Nein | Nein | beide ✓ |
| Insider-only | „Acme Therapeutics Director Reports Open-Market Purchase of 100,000 Shares (Form 4)" | kein Match | Nein | Nein | beide ✓ |

**Gesamt-Kennzahlen (alle 18 Fälle × 2 Modi):**

| Fast | Agentic | Halluzinationen | Clamp-Eingriffe |
|:--:|:--:|:--:|:--:|
| **78 %** | **89 %** | **0** | **9 / 32** |

---

**Lesehilfe (30 Sekunden):** Die vier *Nicht*-Katalysatoren (Analyst, Konferenz, negativ, Insider) lehnen
**beide** Modi korrekt ab — der Regex-Filter deckelt sie auf Stärke ≤ 1. Die zwei *echten* Katalysatoren
(FDA-Zulassung, Lizenzdeal) unterschätzt **fast** (LLM-Rohstärke 2 → kein Match), während **agentic** beide
erkennt. Genau diese zwei Zeilen sind der Unterschied zwischen 78 % und 89 % — agentic ist genauer, **ohne**
mehr Fehlalarme und bei **null** Halluzinationen.

**Herkunft (Transparenz):** real aus dem Juni-Lauf = Partnership, Analyst, Konferenz · kategorie-typisch
konstruiert (real gegen `qwen3:14b` gelaufen) = FDA-Zulassung, negative News, Insider — weil die Validierung
für diese drei Kategorien keine echten Headlines enthielt (siehe [refactor_validation.md](refactor_validation.md) §3).

**Warum hat fast versagt?** Dem `fast`-Pfad fehlt `think:false` (Befund A) — ein Pfad-Tuning-Defekt, kein
Modellproblem. `agentic` setzt es und urteilt beim identischen Input korrekt.

---

## Folie 2 — Vollständige Validierung (alle 18 Testfälle)

> Woher kommen 78 % / 89 % / 9·32 / 0: jede Zeile ist ein realer Validierungslauf (fast UND agentic gegen qwen3:14b).
> „Fast"/„Agentic" = Urteil des Modells (Match Ja/Nein). Werte 1:1 aus [refactor_nl_validation_raw.json](evidence/refactor_nl_validation_raw.json).

| Fall | Kategorie | Erwartung | Fast | Agentic | Clamp | Korrekt |
|:--:|---|:--:|:--:|:--:|:--:|:--:|
| 01 | Phase-1-Daten | Match | Nein | Nein | Ja | beide ✗ |
| 02 | Lizenzdeal / Partnerschaft | Match | Nein | Ja | Ja | nur agentic ✓ |
| 03 | Phase-3-Topline | Match | Ja | Ja | Ja | beide ✓ |
| 04 | FDA-Zulassung | Match | Nein | Ja | Ja | nur agentic ✓ |
| 05 | Klin. Daten (Regex-Lücke) | Match | Nein | Nein | Ja | beide ✗ |
| 06 | Konferenz | kein Match | Nein | Nein | Nein | beide ✓ |
| 07 | Konferenz | kein Match | Nein | Nein | Nein | beide ✓ |
| 08 | Konferenz | kein Match | Nein | Nein | Nein | beide ✓ |
| 09 | Analyst (PT-Erhöhung) | kein Match | Nein | Nein | Ja | beide ✓ |
| 10 | Analyst (Coverage) | kein Match | Nein | Nein | Nein | beide ✓ |
| 11 | Analyst (Reiterate) | kein Match | Nein | Nein | Nein | beide ✓ |
| 12 | Phase-3-Fehlschlag | kein Match | Nein | Nein | Nein | beide ✓ |
| 13 | Clinical Hold | kein Match | Nein | Nein | Nein | beide ✓ |
| 14 | Insider-Kauf | kein Match | Nein | Nein | Nein | beide ✓ |
| 15 | Insider-Kauf | kein Match | Nein | Nein | Ja | beide ✓ |
| 16 | Konferenz + Analyst | kein Match | Nein | Nein | Ja | beide ✓ |
| 17 | Phase-2 + Klage | Match | Ja | Ja | Nein | beide ✓ |
| 18 | Partnerschaft * | Match | Ja | Ja | Nein | beide ✓ |

**Zusammenfassung (direkt aus der Tabelle):**

| Fast | Agentic | Clamp | Halluzinationen |
|:--:|:--:|:--:|:--:|
| **14 / 18 = 78 %** | **16 / 18 = 89 %** | **9 / 32** | **0** |

- **78 %** = 14 korrekte fast-Urteile von 18 (falsch: 01, 02, 04, 05).
- **89 %** = 16 korrekte agentic-Urteile von 18 (falsch: nur 01, 05).
- **Clamp 9/32**: Eingriff in 8 Fällen (01, 02, 03, 04, 05, 09, 15, 16); Fall 01 in beiden Modi → 9 Eingriffe. Nenner 32 = LLM-Läufe (36 − 4 no_signal-Läufe der negativen Fälle 12/13).
- **0 Halluzinationen**: kein Match bzw. final ≥ 3 auf einer Schlagzeile mit Regex-Basis 0.

_Fall 18 (*): Kriterium „Partnerschaft/Lizenzdeal" (konfigurierbares Ziel), nicht „Turnaround"._
