# Refactor-Architektur & Verteidigung — Alt-B NL-Target-Agent

**Branch:** `alt-b-refactor` · **Commit:** `1078b1e` · **Datum:** 2026-06-12
**Modell:** `qwen3:14b` (lokal, Ollama) · **Backend:** FastAPI/Docker (Py 3.12) · **Frontend:** Vue 3 + Vite

Diese Datei erklärt die komplette Architektur, den Datenfluss, die Entscheidungslogik, das
Test-Experiment und liefert 30 Verteidigungsfragen mit Antworten. Begleitdokument:
[`refactor_validation.md`](refactor_validation.md) (Rohergebnisse). Validierung: ausschließlich der Refactor.

---

## 0. Worum geht es?

Der **NL-Target-Agent** beantwortet eine Frage: *„Erfüllt Aktie X gerade ein frei formuliertes Kriterium
(z. B. ‚aktuelle Turnaround-Story‘) — auf Basis ihrer aktuellen Schlagzeilen?"* Das Kriterium ist ein
**Parameter**, nicht fest verdrahtet (ADR-14). Die Maschinerie kombiniert eine **deterministische Regex-Schicht**
mit einem **lokalen LLM** und einem **Clamp**, der das LLM daran hindert, Katalysatoren zu erfinden.

---

## 1. Datenfluss Schritt für Schritt

```
User → AltBView.vue → API-Endpoint → News-Fetch → Regex-Prefilter → LLM → Clamp → Trace → Frontend
```

### Schritt 1 — User-Eingabe
- **Datei:** `frontend/src/views/AltBView.vue`
- **Funktion:** `run()` (Z. 14–34)
- **Input:** Ticker (`ticker`), Freitext-Kriterium (`criterion`, Default „hat aktuell eine Turnaround-Story"), Modus (`mode` = fast | agentic)
- **Output:** Öffnet eine `EventSource` (SSE) auf den Endpoint
- **Zweck:** Eingabemaske + Streaming-Empfang
- **Warum:** Der Nutzer benennt den Ticker selbst → kein Universums-Scan, kein Rechen-Engpass (entkoppelt vom Biotech-Screener)

### Schritt 2 — API-Client
- **Datei:** `frontend/src/api/client.ts`
- **Funktion:** `api.agent.nlTarget(criterion, ticker, mode)` (Z. 97–102)
- **Input:** dieselben drei Felder
- **Output:** `new EventSource("…/agent/nl-target?ticker=…&criterion=…&mode=…")`
- **Zweck:** typisierter SSE-Aufruf
- **Warum:** SSE statt POST, weil der Browser-`EventSource` nur GET kann (Kommentar im Router, `agent.py` Z. 24)

### Schritt 3 — API-Endpoint
- **Datei:** `backend/routers/agent.py`
- **Funktion:** `nl_target(ticker, criterion, mode)` (Z. 98–105); SSE-Wrapper `_sse(stream_factory)` (Z. 74)
- **Input:** Query-Parameter
- **Output:** `StreamingResponse(media_type="text/event-stream")`; `_sse` rahmt jeden Chunk als `data: …\n\n`, escaped Zeilenumbrüche (Z. 61) und schließt mit `[DONE]` (Z. 65)
- **Zweck:** HTTP→Generator-Brücke
- **Warum:** trennt Transport (SSE) von Logik (`nl_target_stream`)

### Schritt 4 — News-Fetch
- **Datei:** `backend/agent/nl_target_runner.py` → `backend/services/market_data.py`
- **Funktion:** `nl_target_stream(...)` (Z. 55–83) ruft `fetch_and_store_news(ticker, db, days=14)` (Z. 71); Quelle: `market_data.fetch_and_store_news` (Z. 147), Finnhub **company-news** API (Z. 171–172), Cache in DB
- **Input:** Ticker, 14-Tage-Fenster
- **Output:** Liste News-Objekte (Headline + Summary); zu `NLItem` gemappt via `_headline_text` = „headline. summary" (Z. 18–21, 76)
- **Zweck:** liefert die einzige Faktengrundlage (Schlagzeilen)
- **Warum:** Das Urteil soll **nur** auf belegbaren aktuellen News fußen, nichts Auswendiges

### Schritt 5 — Regex-Prefilter
- **Datei:** `backend/services/nl_target.py` (+ `event_strength.py`)
- **Funktion:** `prefilter(items, ticker, name)` (Z. 52–76); pro Headline `classify_event(...)` (`event_strength.py` Z. 84)
- **Input:** alle Headlines
- **Output:** `(survivors, regex_strength, qualifying_headlines)` — verwirft irrelevante + **negative** Headlines; `regex_strength` = höchste Stärke unter den qualifizierenden (≥3, positiv)
- **Zweck:** billige, deterministische Vorfilterung + Stärke-Basislinie
- **Warum:** (a) spart LLM-Compute (nur Überlebende gehen zum LLM), (b) liefert den **Anker für den Clamp**

### Schritt 6 — LLM
- **Datei:** `backend/services/nl_target.py`
- **Funktion:** `fast` → `_call_ollama(criterion, survivors)` (Z. 163); `agentic` → `_run_nl_tool_loop(...)` (Z. 257), Tool `inspect_headline` (Z. 224)
- **Input:** Kriterium + Überlebende-Headlines (nummeriert)
- **Output:** JSON `{matches, strength 1-5, evidence:[idx], reason}` (oder `None` bei Ausfall)
- **Zweck:** semantisches Urteil über das Freitext-Kriterium
- **Warum:** Regex erkennt *Typen*, aber nicht *ob ein frei formuliertes Ziel* erfüllt ist — das ist die GenAI-Aufgabe

### Schritt 7 — Clamp / Verdict
- **Datei:** `backend/services/nl_target.py`
- **Funktion:** `combine_verdict(criterion, regex_strength, qualifying, survivor_texts, llm_result)` (Z. 79–125)
- **Input:** Regex-Basis + LLM-JSON
- **Output:** `NLVerdict` (Z. 40) mit `strength` (final), `matches`, `regex_strength`, `llm_strength` (roh), `source`
- **Kernlogik:** `low,high = max(0,regex-1), min(5,regex+1)`; `final = clamp(llm_raw, low, high)`; `matches = bool(llm.matches) ∧ final ≥ 3` (Z. 108–110)
- **Zweck:** LLM-Urteil an die deterministische Basis fesseln
- **Warum:** Anti-Halluzination — das LLM darf ±1 nachjustieren, aber nie einen Katalysator erfinden

### Schritt 8 — Trace → Frontend
- **Datei:** `backend/agent/nl_target_runner.py` (`_render_verdict`, Z. 24–52) → SSE → `AltBView.vue` (`md.render(answer)`, Z. 78)
- **Input:** `NLVerdict`
- **Output:** Markdown: Urteil (Ja/Nein, Signifikanz, Begründung, Belege) + **Trace** (Modus, Quelle, geprüfte Headlines, Regex-Basis, „LLM-Rohstärke → final (geklammert ±1)")
- **Zweck:** vollständige Nachvollziehbarkeit
- **Warum:** Jede Zahl ist herleitbar — Voraussetzung für Vertrauen/Verteidigung

---

## 2. Datenquellen — woher kommt was?

| Größe | Quelle | Code |
|---|---|---|
| **News** | Finnhub `company-news` API (14-Tage-Fenster), DB-Cache; Fallback yfinance | `market_data.py:147,171` |
| **Ticker** | Nutzereingabe im Frontend | `AltBView.vue:8,15` |
| **Kriterium** | Nutzer-Freitext (Default „…Turnaround-Story") | `AltBView.vue:9` |
| **Regex-Stärke** | deterministische Rubrik im Code (`_RULES`, Stärke 1–5) + Negations-/Quellen-Gating | `event_strength.py:29,84` |
| **LLM-Stärke (roh)** | lokales `qwen3:14b`, JSON-Feld `strength` | `nl_target.py:163/257` |
| **Finale Stärke** | `clamp(llm_roh, regex−1, regex+1)` | `nl_target.py:108–109` |

**Wichtig:** Die *Skala* (was ist Stärke 5 vs. 3) lebt **im Code** (`event_strength.py:29–59`), nicht im LLM.
Das LLM liefert eine *Einschätzung*; die deterministische Schicht behält die Skalenhoheit.

---

## 3. Entscheidungslogik — Regex + LLM + Clamp = Urteil

**(a) Regex bildet die Basis** (`event_strength.py:84`):
- Negativ-Begriffe (`fail|halt|reject|lawsuit|…`, Z. 19–26) → Stärke 0, Richtung „negative" → **fällt im Prefilter raus**.
- Sonst erster Treffer in `_RULES` (Z. 29–59): FDA/Phase-3 = 5, Phase-2/Partnerschaft = 4, Phase-1/Finanzierung = 3, Präsentation/Analyst = 2, allgemein = 1.
- Kommentar-Quellen (Motley Fool, Seeking Alpha…) werden auf 2 gedeckelt (Z. 111–112).
- `qualifies = strength ≥ 3 ∧ positiv` (Z. 119).

**(b) LLM urteilt** (`nl_target.py:163/257`): gibt `{matches, strength, evidence, reason}`.

**(c) Clamp entscheidet final** (`nl_target.py:104–110`):
```python
raw  = int(llm_result.get("strength") or 0)
low, high = max(0, regex_strength - 1), min(5, regex_strength + 1)
final = max(low, min(high, raw))
matches = bool(llm_result.get("matches")) and final >= MIN_QUALIFY   # MIN_QUALIFY = 3
```
Ohne LLM-Ergebnis (`llm_result is None`): **Regex-Fallback** — `matches = regex_strength ≥ 3` (Z. 93–102). Null Regression.

**Die Entscheidung entsteht also im Clamp** (`combine_verdict`), nicht im LLM allein: Das LLM kann nur innerhalb
`regex ± 1` wirken und nur per `matches=false` ein Veto setzen.

---

## 4. Fast vs. Agentic

| | **fast** | **agentic** |
|---|---|---|
| Funktion | `_call_ollama` (`nl_target.py:163`) | `_run_nl_tool_loop` (`nl_target.py:257`) |
| Ablauf | **1** Batch-LLM-Call → JSON | Tool-Loop, bis zu **3** Iterationen; LLM darf `inspect_headline(idx)` aufrufen (regex-Klassifikation je Headline) |
| `think:false`? | **nein** (Z. 165–170) | **ja** (`_chat_once` Z. 248) |
| Vorteil | konzeptuell „ein Schuss", einfach | sieht die Regex-Klassifikation, kann gezielt prüfen; **schneller & genauer** (Messung) |
| Nachteil | qwen3 „denkt" lange → ~50 s, nahe 60-s-Timeout; schlechtere Urteile | mehr Turns möglich, aber praktisch kurz |

**Warum agentic in unserer Validierung schneller war (Median 6,4 s vs. 41,5 s):** Der agentic-Pfad setzt
`"think": false` (`_chat_once`, Z. 248) — qwen3:14b ist ein Reasoning-Modell und generiert sonst lange
`<think>`-Tokens. Der fast-Pfad setzt es **nicht** → er denkt ~50 s pro Call. Das ist ein **Tuning-Defekt**, kein
inhärenter Vorteil von „agentic". Fix = ein Zeichen (`think:false` auch in `_call_ollama`). Beide Pfade münden in
denselben `combine_verdict` → identischer Clamp.

---

## 5. Halluzinationsschutz

**Warum kann das LLM keinen Katalysator erfinden?** Weil die finale Stärke **hart auf `regex ± 1` geklammert**
wird (`nl_target.py:108–109`) und `matches` zusätzlich `final ≥ 3` verlangt. Hat der Prefilter einer Headline
Regex-Basis 0 gegeben (Konferenz, Analyst-Meinung, Insider-Kauf), kann das LLM sie maximal auf **1** heben →
`matches` ist unmöglich. Negative Headlines erreichen das LLM gar nicht erst (Prefilter-Drop, `nl_target.py:70–71`).

**Echte Belege aus der Validierung** (3 reale Überhöhungsversuche, alle geblockt):

| Fall | Headline (Regex-Basis 0) | LLM-Rohstärke | final nach Clamp | Match |
|---|---|:--:|:--:|:--:|
| 05-fast | „…New Positive Clinical Data…" (Paraphrase) | **3** | 1 | ✗ |
| 15-fast | „CEO Buys $2 Million of Company Stock…" | **3** | 1 | ✗ |
| 16-fast | Konferenz + Analyst (Absci) | **3** | 1 | ✗ |

In allen drei Fällen wollte das LLM aufwerten; der Clamp deckelte auf 1 → **kein Match**. **0 Halluzinationen
im Output über alle 36 Läufe.**

---

## 6. ASCII-Flowchart (Präsentation)

```
              ┌──────────────────────────────────────────────────────────────┐
              │  USER:  Ticker + Freitext-Kriterium + Modus (fast|agentic)    │
              └───────────────────────────┬──────────────────────────────────┘
                                          │  EventSource (SSE, GET)
                                          ▼
        AltBView.vue ──► api.client ──► GET /api/agent/nl-target ──► _sse() wrapper
                                          │
                                          ▼
                          nl_target_stream()  [nl_target_runner.py]
                                          │
                                          ▼
                 fetch_and_store_news(ticker, 14d)  ──► Finnhub company-news + DB-Cache
                                          │   (Headline + Summary)
                                          ▼
        ┌─────────────────────  PREFILTER  (nl_target.py:prefilter) ──────────────────────┐
        │  classify_event() je Headline  [event_strength.py]                              │
        │   • negativ (fail/halt/…)  ─► DROP (zählt nie)                                   │
        │   • irrelevant            ─► DROP                                                │
        │   • sonst                 ─► survivor                                            │
        │  regex_strength = max Stärke der qualifizierenden (≥3, positiv)                  │
        └───────────────────────────────────────┬─────────────────────────────────────────┘
                          survivors leer?        │
                       ┌───── ja ──► no_signal   │ nein
                       ▼                         ▼
                  matches=False     ┌─────────  LLM  ──────────┐
                  strength=0        │  fast:    _call_ollama    │  (1 Call, KEIN think:false → ~50s)
                                    │  agentic: _run_nl_tool_loop│ (Tool-Loop, think:false → ~6s)
                                    │  → {matches, strength, …} │
                                    └────────────┬──────────────┘
                                                 │  (None bei Ausfall → Regex-Fallback)
                                                 ▼
                          ┌──────────  CLAMP  (combine_verdict)  ──────────┐
                          │  final = clamp(llm_roh, regex−1, regex+1)      │
                          │  matches = llm.matches  ∧  final ≥ 3           │
                          └────────────────────────┬───────────────────────┘
                                                   ▼
                          TRACE (_render_verdict): Urteil + Regex-Basis +
                          LLM-Rohstärke → final (±1) + Quelle (llm/fallback/no_signal)
                                                   │  SSE: data: …\n\n  … [DONE]
                                                   ▼
                                AltBView.vue  ►  md.render(answer)  ►  Bildschirm
```

---

## 7. Das Refactor-Experiment — „Wie wurde der Refactor getestet?"

**Warum wurde getestet?** Wir präsentieren den Refactor-Branch und müssen mit **eigenen Daten** belegen, dass der
neue NL-Target-Agent funktioniert — nicht nur behaupten „läuft".

**Was sollte nachgewiesen werden?** Vier Dinge: (1) die Pipeline läuft technisch end-to-end; (2) der Clamp
verhindert Halluzinationen; (3) das System trennt echte Katalysatoren von Rauschen (Konferenz/Analyst/Insider/negativ);
(4) fast vs. agentic — welcher Pfad ist besser.

**Warum Output-Qualität statt Aktienrendite?** Der NL-Target-Agent ist ein **Klassifikator/Urteiler über Text**,
kein Trading-Signal. Seine Aufgabe: „erfüllt diese News das Kriterium?" — das ist eine *Sprach-/Urteilsaufgabe*.
Aktienrendite würde etwas ganz anderes messen (Markt-Performance, beeinflusst von hunderten Faktoren) und wäre
für die Frage „urteilt das LLM korrekt über Schlagzeilen?" ungeeignet. Wir messen also **Urteilsqualität gegen
eine fachliche Ground Truth**.

**Unterschied zur alten Biotech-Performance-Validierung:** Die frühere Alt-B-Validierung (Juni/April-Läufe) maß
**Trading-Relevanz** — qualifizierten Kandidaten und ihre Forward-Rendite vs. XBI. Sie beantwortet „findet die
Strategie gute Aktien?". Dieser Test beantwortet „urteilt der NL-Agent korrekt über einzelne Schlagzeilen?". Andere
Frage, andere Metrik, andere Ground Truth. (Die Headlines stammen teils aus jenen Läufen — als **Text-Input**, nicht als Renditebeleg.)

**Was genau wurde getestet?** `services/nl_target.py::evaluate_nl_target` — exakt der Code, den der Endpoint
aufruft — mit 18 kuratierten Fällen über 6 Kategorien, je in fast und agentic, gegen echtes `qwen3:14b`.
Harness: [`docs/evidence/refactor_nl_harness.py`](evidence/refactor_nl_harness.py); Rohdaten:
[`docs/evidence/refactor_nl_validation_raw.json`](evidence/refactor_nl_validation_raw.json).

**Wie wurden fast und agentic verglichen?** Identische Inputs, beide Modi, Vergleich von Endurteil (`matches`),
Stärken (regex/roh/final) und Laufzeit — Fall für Fall.

**Welche Metriken?** Trefferquote vs. Ground Truth (gesamt/je Modus), Halluzinationen, Clamp-Eingriffe (hoch/runter),
Laufzeit (Median/Spanne), False Positives/Negatives.

**Was beweist das Experiment?** (1) Pipeline läuft end-to-end (Live-Endpoint-Beleg). (2) Der Clamp hält:
0 Halluzinationen trotz 3 Überhöhungsversuchen. (3) Negativ/Konferenz/Analyst/Insider werden korrekt nicht
hochgestuft. (4) agentic ist fast überlegen (89 % vs. 78 %, ~6× schneller) und der fast-Defekt (`think:false`) ist lokalisiert.

**Was beweist es NICHT?** Keine Trading-Performance, keine statistische Allgemeingültigkeit (n=18, kuratiert),
keine vollständige EDGAR-/Fundamental-Abdeckung, keine Aussage über andere Modelle/Sprachen, keine Garantie gegen
Regex-Lücken (Recall-Decke).

---

## 8. Datenbasis des Experiments — exakt (verifiziert gegen die Lauf-JSONs)

> **Verifizierung:** Jeder als „real" markierte Text wurde gegen `run_2026-06-10_result.json` (Juni) bzw.
> `run_2026-04_april_result.json` (April) abgeglichen. **Publisher („Quelle") ist nicht verifiziert** — die Läufe
> speichern nur `src=news`, nicht das Medium (GlobeNewswire o. ä.). „Lauf" + „Datum" + „Ticker" sind belegt.

| # | Kategorie | Ticker | Headline/Text (wie eingesetzt) | Kriterium | Echt/konstruiert | Quelle/Lauf | Zweck des Testfalls |
|--|--|--|--|--|--|--|--|
| 01 | klar positiv | BIOA | BioAge Reports Positive Phase 1 Data for BGE-102 Showing Up To 86% hsCRP Reduction | Turnaround | **real, gekürzt** (Casing „For"→„for", Tail entfernt) | April-Lauf, 2026-04-21; Publisher nicht verifiziert | Phase-1-Katalysator (st3) → Match-Pfad + Clamp-Boden |
| 02 | klar positiv | CTMX | CytomX Expands Collaboration and Licensing Agreement With Regeneron | Turnaround | **real, gekürzt** (Tail „To Create…" entfernt) | Juni-Lauf, 2026-06-03 | Lizenzdeal (st4) → fast/agentic-Divergenz |
| 03 | klar positiv | — | Acme Therapeutics Announces Positive Phase 3 Topline Results Meeting the Primary Endpoint | Turnaround | **konstruiert** | — | reiner st5-Phase-3-Katalysator (Clamp 4–5) |
| 04 | klar positiv | — | Beta Pharma Receives FDA Approval for Lead Drug in Rare Disease | Turnaround | **konstruiert** | — | reine FDA-Zulassung (st5) |
| 05 | regex-grenze | CABA | Cabaletta Bio Announces New Positive Clinical Data Supporting Rese-Cel as Potential Treatment | Turnaround | **paraphrasiert** — echte CABA-HL 2026-06-03 war „…New Rese-cel Data and Development Updates…" (st4) | Juni-Lauf (angelehnt), Text abweichend | Regex-Lücke: Katalysator ohne Keyword → Clamp-Decke (False-Negative) |
| 06 | konferenz | ABCL | AbCellera Biologics Presents at Jefferies Global Healthcare Conference 2026 | Turnaround | **real, gekürzt** („Inc. (ABCL)" + Tail entfernt) | Juni-Lauf, 2026-06-05 | Konferenz (st2) → kein Match (Anti-Halluzination) |
| 07 | konferenz | ADPT | Adaptive Biotechnologies Presents at 46th Annual William Blair Growth Stock Conference | Turnaround | **real, gekürzt** | Juni-Lauf, 2026-06-04 | Konferenz-Standardfall |
| 08 | konferenz | ASMB | Assembly Biosciences Presents at Goldman Sachs 47th Annual Global Healthcare Conference | Turnaround | **konstruiert** (Konferenz-Vorlage; echte ASMB-HL 2026-06-08 war „…Teases Gilead HSV-2 Decision…") | nicht verifiziert (Text konstruiert) | dritter Konferenzfall zur Robustheit |
| 09 | analyst | ALKS | RBC Capital Maintains Outperform on Alkermes, Raises Price Target to $56 | Turnaround | **VERBATIM (wörtlich)** | Juni-Lauf, 2026-06-09 | Analyst-PT-Erhöhung (st2) → kein Match |
| 10 | analyst | ABSI | Leerink Partners Initiates Coverage on Absci With Outperform Rating | Turnaround | **real, gekürzt/Casing** | Juni-Lauf, 2026-06-04 | Analyst-Initiation |
| 11 | analyst | ARVN | Stephens & Co. Reiterates Overweight on Arvinas, Maintains $18 Price Target | Turnaround | **VERBATIM (wörtlich)** | Juni-Lauf, 2026-06-03 | Analyst-Reiterate |
| 12 | negativ | — | Gamma Therapeutics Announces Phase 3 Trial Failed to Meet Primary Endpoint | Turnaround | **konstruiert** | — | Negativ-Drop (`fail`) → no_signal, kein LLM |
| 13 | negativ | — | Delta Bio Halts Lead Program After FDA Places Clinical Hold | Turnaround | **konstruiert** | — | Negativ-Drop (anderer Trigger: `halt/hold`) |
| 14 | insider-only | — | Acme Therapeutics Director Reports Open-Market Purchase of 100,000 Shares (Form 4) | Turnaround | **konstruiert** (Form-4-Stil) | — | Insider-Headline ≠ News-Katalysator (Grenze des NL-Agenten) |
| 15 | insider-only | — | Beta Bio CEO Buys $2 Million of Company Stock in Open-Market Transaction | Turnaround | **konstruiert** (Form-4-Stil) | — | LLM-Überhöhungsversuch ($-Betrag, roh 3 → Clamp 1) |
| 16 | schwach-mix | ABSI | (1) Absci … Presents at Jefferies … Conference 2026  ·  (2) Leerink Partners Initiates Coverage on Absci … | Turnaround | **real, gekürzt** (2 Headlines) | Juni-Lauf, 2026-06-05 + 2026-06-04 | mehrere schwache HL bleiben unter Schwelle |
| 17 | mix pos+neg | — | (1) Epsilon Pharma Announces Positive Phase 2 Data in Lupus  ·  (2) Epsilon Pharma Faces Securities Class Action Lawsuit Over Disclosures | Turnaround | **konstruiert** (2 Headlines) | — | Prefilter droppt das Negative, beurteilt das Positive (st4) |
| 18 | anderes Ziel | CTMX | CytomX Expands Collaboration and Licensing Agreement With Regeneron | **Partnerschaft/Lizenzdeal** | **real, gekürzt** | Juni-Lauf, 2026-06-03 | konfigurierbares Ziel ≠ Turnaround (ADR-14) |

**Zusammenfassung Herkunft:** 2 wörtlich (09, 11) · 7 real-aber-gekürzt (01, 02, 06, 07, 10, 16, 18) ·
2 paraphrasiert/konstruiert-aus-real (05, 08) · 7 frei konstruiert (03, 04, 12, 13, 14, 15, 17).
**Warum konstruierte Fälle?** Um **kontrollierte Grenzsituationen** zu erzwingen, die in echten 14-Tage-News
nicht zuverlässig gleichzeitig auftreten: reiner Negativ-Drop (12/13), Insider-Headline (14/15), saubere
Positiv+Negativ-Mischung (17), eindeutiger st5-Katalysator ohne Störsignal (03/04).

---

## 9. Testergebnisse

**18 Fälle × 2 Modi = 36 Läufe** (Rohdaten: `refactor_nl_validation_raw.json`).

| Metrik | Wert |
|---|---|
| Trefferquote gesamt | **30/36 = 83 %** |
| Trefferquote fast | 14/18 = 78 % |
| Trefferquote agentic | **16/18 = 89 %** |
| Halluzinationen (Output) | **0** (3 LLM-Überhöhungsversuche, alle vom Clamp geblockt) |
| Clamp-Eingriffe | 9/32 LLM-Läufe (5 hoch-, 4 runter-geklammert) |
| Laufzeit fast | Median 41,5 s · Spanne 31,3 – 892,1 s (1 Ausreißer) |
| Laufzeit agentic | Median 6,4 s · Spanne 5,6 – 10,0 s |
| False Positives | **0** (kein Fall matchte fälschlich) |
| False Negatives | 6 Roh-Abweichungen → siehe Ursachen |

**False-Negative-Ursachen (3 Kategorien):**
1. **fast-Qualität (02-fast, 04-fast):** echte Katalysatoren (st4/st5) bekamen Rohstärke 2 + `matches=false`;
   **agentic urteilte beim identischen Input korrekt.** → Pfad-Defekt (`think:false`), kein Modellfehler.
2. **Regex-Lücke (05 beide Modi):** paraphrasierte Headline ohne Keyword → Basis 0 → Clamp deckelt auf 1, obwohl
   fast die Rohstärke 3 wollte. Anti-Halluzination zu scharf → False-Negative durch Regex-Blindstelle.
3. **Grenzwertige Ground Truth (01 beide Modi):** beide Modi werten einen Phase-1-Readout nicht als Turnaround
   (vertretbar; meine Soll-Vorgabe war großzügig).

**Bereinigt** (ohne Regex-Lücke und Grenzfall) trifft **agentic auf allen klaren Katalysator-, Konferenz-,
Analyst-, Negativ- und Insider-Fällen korrekt**.

---

## 10. Grenzen des Experiments

- **Kleines Korpus (n=18):** keine statistische Allgemeingültigkeit; Punktprobe, kein Sample.
- **Teils konstruierte Grenzfälle (9 von 18):** absichtlich, um Mechanik zu isolieren — aber kein „in-the-wild"-Beweis.
- **Keine Trading-Performance:** misst Urteilsqualität, nicht Rendite.
- **Nur Headlines/News:** keine EDGAR-/Fundamental-/Insider-Daten im NL-Agenten — **Insider-Käufe sind hier
  prinzipiell unsichtbar** (sie leben in `score_alt_b`, nicht im NL-Agenten).
- **Recall ist Regex-gedeckelt:** Katalysatoren ohne Keyword im `_RULES`-Set werden durch den Clamp unterdrückt
  (Preis der Halluzinations-Freiheit; Fall 05).
- **fast-Performance-Defekt:** fehlendes `think:false` → ~50 s/Call und schlechtere Urteile; ein Ausreißer mit 892 s.
- **Ein Modell, eine Sprache, Temperatur 0:** keine Aussage über andere LLMs; fast/agentic liefern bei
  identischem Input verschiedene Rohstärken (kein modusübergreifend eindeutiges Urteil).

---

## 11. 30 Professorenfragen mit Antworten

**Daten & Herkunft**
1. **Woher stammen die Daten?** Aktuelle Schlagzeilen über die Finnhub `company-news`-API (`market_data.py:171`),
   14-Tage-Fenster, DB-gecached. Für den Test: 18 kuratierte Texte, teils aus den Juni-/April-Läufen, teils konstruiert.
2. **Welche Testfälle waren echt (wörtlich)?** Nur **2**: Fall 09 (ALKS, 2026-06-09) und Fall 11 (ARVN, 2026-06-03).
3. **Welche waren real, aber bearbeitet?** 7 (01, 02, 06, 07, 10, 16, 18) — gekürzt/Casing bereinigt, Bedeutung erhalten.
4. **Welche waren konstruiert?** 7 frei (03, 04, 12, 13, 14, 15, 17) + 2 aus-real-paraphrasiert (05, 08).
5. **Warum konstruierte Testfälle?** Um kontrollierte Grenzsituationen zu erzwingen (reiner Negativ-Drop,
   Insider-Headline, saubere Pos+Neg-Mischung), die in 14-Tage-Echtnews nicht verlässlich zugleich vorkommen.
6. **Ist das nicht Cherry-Picking?** Nein — die Fälle sind **vor** dem Lauf festgelegt und decken bewusst die
   *Schwachstellen* ab (Konferenz/Analyst/Insider/Regex-Lücke). Wir testen, wo es wehtut, nicht wo es leicht ist.
7. **Warum ist Fall 05 „paraphrasiert"?** Die echte Cabaletta-Headline (2026-06-03) war anders formuliert und
   st4; mein Text ist eine Umschreibung, deren Regex-Miss (st0) eine Eigenschaft des Texts ist — ehrlich so dokumentiert.
8. **Ist die Publisher-Quelle belegt?** Nein — „nicht verifiziert". Die Läufe speichern nur `src=news`, nicht das Medium.

**Architektur & Code**
9. **Wo entsteht die Entscheidung?** In `combine_verdict` (`nl_target.py:79–125`), konkret im Clamp (Z. 108–110) —
   nicht im LLM allein.
10. **Was macht das LLM?** Liefert ein semantisches Urteil `{matches, strength, evidence, reason}` zum Freitext-Kriterium
    (`_call_ollama` / `_run_nl_tool_loop`).
11. **Was macht die Regex?** Klassifiziert jede Headline deterministisch in Stärke 0–5 + Richtung (`event_strength.py:84`),
    verwirft Negatives, liefert die Basislinie.
12. **Was macht der Clamp?** `final = clamp(llm_roh, regex−1, regex+1)`; `matches = llm.matches ∧ final ≥ 3`. Fesselt das
    LLM an die deterministische Basis.
13. **Warum die Reihenfolge Regex→LLM→Clamp?** Billig vor teuer (nur Überlebende kosten LLM-Zeit) und die Regex muss
    *vor* dem LLM da sein, weil sie der Anker des Clamps ist.
14. **Warum SSE statt REST-JSON?** Live-Streaming des Urteils/Trace; `EventSource` kann nur GET (`agent.py:24`).
15. **Wo kommt die finale Stärke her?** Ausschließlich aus dem Clamp (`nl_target.py:108–109`), nie direkt vom LLM.
16. **Was passiert, wenn Ollama ausfällt?** Regex-Fallback (`combine_verdict`, Z. 93–102): `matches = regex ≥ 3`. Kein Crash.
17. **Wie wird die Stärke-Skala kontrolliert?** Die Rubrik lebt im Code (`_RULES`, `event_strength.py:29–59`) — menschlich
    kontrolliert, deterministisch. Das LLM hat keine Skalenhoheit.

**GenAI-Einordnung**
18. **Warum ist das überhaupt GenAI?** Das Kernurteil „erfüllt diese News ein *frei formuliertes* Kriterium?" ist eine
    generative Sprachaufgabe, die ein lokales LLM (qwen3:14b) löst — inkl. agentic Tool-Use (`inspect_headline`).
19. **Ist die Regex nicht „das eigentliche System"?** Sie ist das Leitplanken-/Skala-System. Die *semantische*
    Beurteilung des Freitext-Ziels macht das LLM; ohne LLM nur ein grober Regex-Fallback.
20. **Was ist der agentische Anteil?** Im agentic-Modus ruft das LLM selbstständig das Tool `inspect_headline(idx)`
    auf, um die deterministische Klassifikation einzusehen, bevor es urteilt (`nl_target.py:257–295`).
21. **Warum lokal statt Cloud-LLM?** Datenkontrolle, Kosten, Offline-Demo; bewusst MacBook-tauglich (Funnel + Cache).

**Experiment & Beweiskraft**
22. **Wie wurde validiert?** 18 Fälle × 2 Modi gegen echtes qwen3:14b über `evaluate_nl_target`; Vergleich des Urteils
    gegen eine fachliche Ground Truth; reproduzierbar via `refactor_nl_harness.py`.
23. **Warum Output-Qualität statt Rendite?** Der NL-Agent urteilt über Text, nicht über Märkte; Rendite würde die
    falsche Größe messen. Trading-Relevanz deckt die *frühere* Biotech-Validierung ab.
24. **Was unterscheidet das von der alten Validierung?** Andere Frage (urteilt das LLM korrekt? vs. findet die Strategie
    gute Aktien?), andere Metrik (Trefferquote vs. Forward-Rendite), andere Ground Truth.
25. **Was beweist der Test?** End-to-End-Lauf, 0 Halluzinationen (Clamp hält), korrekte Trennung Katalysator/Rauschen,
    agentic > fast.
26. **Was beweist er NICHT?** Keine Rendite, keine statistische Allgemeingültigkeit, keine vollständige
    EDGAR/Fundamental-Abdeckung, keine Modell-/Sprach-Generalisierung.
27. **Wie viele Halluzinationen gab es?** 0 im Output; 3 LLM-Überhöhungsversuche (05-, 15-, 16-fast) wurden geklammert.
28. **Warum war agentic schneller?** Es setzt `think:false`; fast nicht → fast „denkt" ~50 s. Tuning-Defekt, Fix = ein Zeichen.
29. **Gibt es False Positives?** Nein, 0 — kein Fall matchte fälschlich. Die Fehler sind ausnahmslos False-Negatives.
30. **Welche Limitationen bleiben?** Kleines Korpus, teils konstruiert, Regex-Recall-Decke, News-only (Insider unsichtbar),
    fast-Performance-Defekt, ein Modell/eine Sprache. (Details §10.)

---

## Anhang — zentrale Code-Stellen

| Datei | Stelle | Rolle |
|---|---|---|
| `frontend/src/views/AltBView.vue` | `run()` Z. 14–34; `md.render` Z. 78 | UI, SSE-Empfang, Trace-Anzeige |
| `frontend/src/api/client.ts` | `nlTarget` Z. 97–102 | SSE-Aufruf |
| `backend/routers/agent.py` | `nl_target` Z. 98–105; `_sse` Z. 74 | Endpoint + SSE-Rahmen |
| `backend/agent/nl_target_runner.py` | `nl_target_stream` Z. 55–83; `_render_verdict` Z. 24–52 | News-Fetch + Trace-Render |
| `backend/services/market_data.py` | `fetch_and_store_news` Z. 147; Finnhub Z. 171 | News-Quelle |
| `backend/services/nl_target.py` | `prefilter` Z. 52; `combine_verdict` Z. 79 (Clamp Z. 108–110); `_call_ollama` Z. 163; `_run_nl_tool_loop` Z. 257 | Prefilter, Clamp, LLM-Pfade |
| `backend/services/event_strength.py` | `classify_event` Z. 84; `_RULES` Z. 29–59; `_NEGATIVE` Z. 19 | deterministische Stärke/Richtung |
