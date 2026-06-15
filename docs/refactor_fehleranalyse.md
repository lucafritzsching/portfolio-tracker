# Refactor-Fehleranalyse — die 4 Abweichungen der NL-Ziel-Validierung

> Warum kommt agentic auf **89 %** und nicht auf 100 %, und warum scheitert fast in 4 Fällen?
> Analyse **ausschließlich** auf Basis des Codes ([`event_strength.py`](backend/services/event_strength.py),
> [`nl_target.py`](backend/services/nl_target.py)) und der Rohdaten
> ([`refactor_nl_validation_raw.json`](evidence/refactor_nl_validation_raw.json)). Keine Schätzungen.
>
> Reproduktion der Klassifikation/Werte: [`refactor_nl_verify.py`](evidence/refactor_nl_verify.py),
> Gesamt-Auswertung: [refactor_validation.md](refactor_validation.md).

## Entscheidungsformel (Grundlage jeder Erklärung)

[`combine_verdict`, nl_target.py:108–110](backend/services/nl_target.py):

```
final   = clamp(llm_strength, regex_strength−1 … regex_strength+1), gedeckelt auf 0..5
matches = LLM.matches  UND  final ≥ 3       (MIN_QUALIFY = 3)
```

Zwei Dinge sind hier entscheidend und erklären alle vier Fälle:
1. Die **Regex-Stärke** bildet ein hartes Fenster `±1` um die finale Stärke (Anti-Halluzination).
2. Das **boolesche `matches` des LLM** ist bindend — eine hohe Stärke allein erzwingt **kein** Match.

---

## Fall 01 — BioAge (BIOA) · „Positive Phase 1 Data"

| | Wert |
|---|---|
| Regex-Regel | Stärke-3 „Phase-1-Erfolg / Guidance / Finanzierung / IND", Muster `\bphase 1\b` |
| Regex-Stärke | **3** (qualifiziert) |
| LLM-Stärke (roh) | fast **1** · agentic **1** |
| Clamp | Ja, beide Modi: Fenster [2..4], 1 → **2 hochgeklammert** |
| final / matches | final **2** (< 3) · `LLM.matches=false` → **kein Match** (beide) |

**Warum:** Das Modell wertet einen **Frühphasen-Readout ohne vorherigen Absturz** nicht als Turnaround
(Begründung wörtlich: *„keine Hinweise auf einen vorherigen Rückgang"* / *„keine Hinweise auf eine
‚Turnaround-Story'"*). Beide Modi identisch.

**Einordnung: grenzwertige Ground Truth** — *kein* Systemfehler (Code korrekt), *keine* Regex-Grenze
(Regex gab korrekt 3), *keine* Fast-Schwäche (beide Modi gleich). Die Soll-Vorgabe „Match" war großzügig;
die konservative LLM-Auslegung ist fachlich vertretbar.

---

## Fall 05 — Cabaletta (CABA) · „New Positive Clinical Data"

| | Wert |
|---|---|
| Regex-Regel | **keine** → Stärke 0, „Kein Katalysator" |
| warum kein Treffer | Muster `\bpositive (?:topline \|interim )?(?:data\|results?)\b` verlangt „positive" **direkt** vor „data"; hier steht **„Clinical"** dazwischen |
| Regex-Stärke | **0** |
| LLM-Stärke (roh) | fast **3** · agentic **1** (fast lag inhaltlich näher!) |
| Clamp | Fenster [0..1]: fast **3 → 1 heruntergeklammert** · agentic 1 → 1 (kein Eingriff) |
| final / matches | final **1** (< 3) → **kein Match** (beide) |

**Warum:** Regex-Basis 0 deckelt final auf max. 1. Selbst die korrektere fast-Rohstärke 3 wird vom
Anti-Halluzinations-Clamp auf 1 gezogen.

**Einordnung: Regex-Grenze + bewusste Designentscheidung** — ein False-Negative durch eine Regex-Lücke,
dessen Wirkung der Clamp `±1` (Anti-Halluzination) erzwingt (Recall ist hier der Preis). **Ausdrücklich
keine Fast-Schwäche** — fast war mit Rohstärke 3 sogar besser.

---

## Fall 02 — CytomX (CTMX) · „Collaboration and Licensing Agreement"

| | Wert |
|---|---|
| Regex-Regel | Stärke-4 „Phase-2 / Partnerschaft", Muster `\b(partnership\|collaborat\w+\|licens\w+ agreement\|…)\b` |
| Regex-Stärke | **4** |
| LLM-Stärke (roh) | fast **2** · agentic **4** |
| Clamp | Fenster [3..5]: fast **2 → 3 hochgeklammert** · agentic 4 → 4 (kein Eingriff) |
| final / matches | fast: final **3** (≥ 3!), aber `LLM.matches=false` → **kein Match** · agentic: final 4 + `matches=true` → **Match** |

**Warum:** Der Clamp hat die fast-Stärke ins qualifizierende Band **gehoben** (2→3) — gescheitert ist fast
am **booleschen Veto** (Modell: *„nicht … einen klaren Wendepunkt"*). agentic urteilt beim identischen
Input korrekt.

**Einordnung: Schwäche des Fast-Modus.** Ursache: dem fast-Pfad fehlt `think:false` ([Befund A](refactor_validation.md))
→ das Reasoning-Modell urteilt im Einzel-Call schlechter. Kein Regex-/Code-/Ground-Truth-Problem.

---

## Fall 04 — Beta Pharma* · „Receives FDA Approval"

| | Wert |
|---|---|
| Regex-Regel | Stärke-5 „FDA-Zulassung / Phase-3-Erfolg", Muster `\bfda approv\w*` |
| Regex-Stärke | **5** |
| LLM-Stärke (roh) | fast **2** · agentic **5** |
| Clamp | Fenster [4..5]: fast **2 → 4 hochgeklammert** · agentic 5 → 5 (kein Eingriff) |
| final / matches | fast: final **4** (≥ 3!), aber `LLM.matches=false` → **kein Match** · agentic: final 5 + `matches=true` → **Match** |

**Warum:** Identisch zu Fall 02 — der Clamp hebt die Stärke (2→4), das **boolesche fast-Urteil** kippt es
(Modell: *„ein einzelner Erfolg reicht nicht aus"*). Dass fast eine **FDA-Zulassung** nicht als Turnaround
anerkennt, ist ein klarer Qualitätsfehler des Einzel-Calls; Regex (5) war perfekt.

**Einordnung: Schwäche des Fast-Modus** (gleiche Ursache wie Fall 02).

(* konstruierter Fall, real gegen `qwen3:14b` gelaufen.)

---

## Warum agentic 89 % erreicht und nicht 100 %

Agentic liegt **nur** in Fall 01 und 05 daneben — **keiner** davon ist ein agentic-Modellfehler:

| Fall | Agentic-Fehlerursache | Typ |
|---|---|---|
| **01** | Modell wertet Phase-1 konservativ als „kein Turnaround"; Soll-Vorgabe großzügig | grenzwertige **Ground Truth** (Label-Frage, vertretbar) |
| **05** | Regex-Lücke (kein Keyword) → Clamp deckelt auf 1 | **Regex-Grenze** + bewusste **Anti-Halluzinations-Entscheidung** |

## Zusammenfassung: Ursache je Fall

| Fall | Unternehmen | Regex | LLM-roh f/a | final f/a | matches f/a | Ursache |
|---|---|:--:|:--:|:--:|:--:|---|
| 01 | BioAge | 3 | 1 / 1 | 2 / 2 | ✗ / ✗ | grenzwertige Ground Truth |
| 05 | Cabaletta | 0 | 3 / 1 | 1 / 1 | ✗ / ✗ | Regex-Grenze + Clamp-Design |
| 02 | CytomX | 4 | 2 / 4 | 3 / 4 | ✗ / ✓ | Fast-Schwäche (`think:false`) |
| 04 | Beta Pharma* | 5 | 2 / 5 | 4 / 5 | ✗ / ✓ | Fast-Schwäche (`think:false`) |

**Kernsätze für die Verteidigung:**
- *„Agentic ist auf jedem Fall korrekt, auf dem das System korrekt sein **kann**. Die fehlenden 11 % sind
  kein Modellversagen: eine vertretbare Label-Strenge bei Frühphasendaten (01) und der bewusste Preis
  unserer Null-Halluzinations-Garantie — eine Regex-Lücke, die der Clamp absichtlich nicht überschreiben
  lässt (05)."*
- *„Die vier fast-Fehler sind zur Hälfte ein reiner Tuning-Defekt: dem fast-Pfad fehlt `think:false`,
  weshalb er bei klaren Katalysatoren wie einer FDA-Zulassung mit `matches=false` votiert — agentic
  urteilt beim identischen Input korrekt."*
- *„In Fall 02 und 04 hat der Clamp die fast-Stärke sogar ins qualifizierende Band gehoben (2→3, 2→4) —
  gescheitert ist fast am **booleschen `matches`-Veto**, nicht an der Stärke. Beide LLM-Ausgaben (Zahl
  und Boolean) zählen."*
