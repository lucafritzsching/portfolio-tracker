# Prüfbericht — Nachrechnung Abschnitt 7 (Refactor-Validierung)

**Geprüftes Dokument:** [refactor_validation.md](refactor_validation.md), Abschnitt 7 (Testergebnisse)
**Rohdaten:** [`docs/evidence/refactor_nl_validation_raw.json`](evidence/refactor_nl_validation_raw.json) — 36 Läufe (18 Fälle × fast/agentic)
**Prüfskript:** [`docs/evidence/refactor_nl_verify.py`](evidence/refactor_nl_verify.py)
**Datum:** 2026-06-13 · **Branch:** `alt-b-refactor`
**Ergebnis:** Alle 6 Kennzahlen sind durch die Rohdaten belegt (Skript-Exit 0). Eine Methodik-Präzisierung beim Median (siehe §6).

## Reproduktion (Dienstag eins zu eins)

```bash
python3 docs/evidence/refactor_nl_verify.py
# Exit 0  =  jede Kennzahl per assert gegen den Berichtswert geprüft und belegt.
```

Das Skript liest ausschließlich die Roh-JSON, rechnet jede Zahl unabhängig neu, druckt Rohdaten-Basis +
Formel + Ergebnis, prüft per `assert` gegen den Berichtswert und gibt am Ende eine **Audit-Tabelle aller
36 Läufe** aus. Kein LLM, keine Netzwerkabrufe — rein deterministisch.

---

## Kennzahl für Kennzahl

Jede Zeile in der Roh-JSON trägt: `mode`, `regex_strength`, `llm_strength`, `final`, `matches`,
`source`, `correct`, `secs`.

### 1. Gesamtquote — 83 % ✅
- **Rohdaten:** Feld `correct` über alle 36 Records.
- **Formel:** `count(correct == true) / 36`
- **Berechnung:** `30 / 36 = 0,83333…`
- **Ergebnis:** **83,33 % → 83 %.** Belegt. (Falsche Fälle: 01, 02, 04, 05.)

### 2. Fast-Quote — 78 % ✅
- **Rohdaten:** `correct` über die 18 Records mit `mode == "fast"`.
- **Formel:** `count(correct == true ∧ mode == fast) / 18`
- **Berechnung:** `14 / 18 = 0,77778…`
- **Ergebnis:** **77,78 % → 78 %.** Belegt. (Falsch: 01, 02, 04, 05.)

### 3. Agentic-Quote — 89 % ✅
- **Rohdaten:** `correct` über die 18 Records mit `mode == "agentic"`.
- **Formel:** `count(correct == true ∧ mode == agentic) / 18`
- **Berechnung:** `16 / 18 = 0,88889…`
- **Ergebnis:** **88,89 % → 89 %.** Belegt. (Falsch: nur 01, 05.)
- **Quergecheckt:** Abweichungen gesamt = fast 4 + agentic 2 = **6** — deckt sich mit „6 Abweichungen" in Abschnitt 4.

### 4. Halluzinationen — 0 ✅
- **Definition (operationalisiert):** Erfundener Katalysator = ein `matches==true` **oder** `final ≥ 3`
  auf einer Schlagzeile mit deterministischer **Regex-Basis 0**.
- **Rohdaten:** `regex_strength`, `llm_strength`, `final`, `matches`.
- **Überhöhungsversuche** (`regex_strength == 0 ∧ llm_strength ≥ 3`): **3** → `05-fast (0/roh 3→final 1)`,
  `15-fast (0/3→1)`, `16-fast (0/3→1)`.
- **Durchgekommen** (`final ≥ 3` oder `matches==true`): **0.**
- **Ergebnis:** **0 Halluzinationen, 3 vom Clamp geblockte Versuche.** Belegt.

### 5. Clamp-Eingriffe — 9 / 32 ✅
- **Nenner 32:** LLM-Läufe = `source == "llm"`. Die 4 Nicht-LLM-Läufe sind `12-fast, 12-agentic,
  13-fast, 13-agentic` (alle `no_signal` — Negative vom Prefilter verworfen, kein LLM-Call). `36 − 4 = 32`.
- **Eingriff:** `final != llm_strength`.
- **Berechnung:** **9 Eingriffe.**
  - **4× runter** (`final < llm_roh`): `05-fast (3→1)`, `09-fast (2→1)`, `15-fast (3→1)`, `16-fast (3→1)`.
  - **5× hoch** (`final > llm_roh`): `01-fast (1→2)`, `01-agentic (1→2)`, `02-fast (2→3)`,
    `03-fast (3→4)`, `04-fast (2→4)`.
- **Ergebnis:** **9/32 (4 runter, 5 hoch).** Belegt.

### 6. Median-Laufzeiten — belegt unter Basis „nur LLM-Läufe" ⚠️
- **Rohdaten:** Feld `secs`.
- **Formel:** Median; bei 16 Werten = Mittel des 8./9., bei 18 Werten = Mittel des 9./10. Werts.
- **Kernpunkt:** Die Bericht-Werte entstehen, wenn man die zwei `no_signal`-Läufe je Modus
  (Fälle 12/13, **0,0 s**, weil ohne LLM-Call) **ausschließt** — konsistent mit den im Bericht genannten
  Spannen (fast `31,3–892,1`, agentic `5,6–10,0`, die die 0,0 s ebenfalls ausnehmen).

| Modus | über **alle 18** Läufe | über die **16 LLM-Läufe** | Bericht sagt |
|---|---|---|---|
| **fast** | 40,15 s | **41,55 s** | 41,5 s |
| **agentic** | 6,35 s | **6,40 s** | 6,4 s |

- **fast (16 LLM-Läufe):** `… 38,8 \| 41,5 \| 41,6 …` → 8./9. Wert = `(41,5 + 41,6)/2 = 41,55 s`.
  (Bericht schreibt 41,5 s; streng gerundet 41,6 s — Differenz 0,05 s, immateriell.)
- **agentic (16 LLM-Läufe):** Median = **6,40 s** (exakt).
- **Ergebnis:** **Median-Zahlen reproduzierbar und korrekt unter der Basis „nur LLM-Läufe (n=16)".**
  Wer naiv alle 18 Zeilen mittelt, erhält 40,15 s / 6,35 s — daher gehört die Basis explizit genannt.

---

## Verifizierte Skript-Ausgabe (2026-06-13)

```
Records  : 36  (fast=18, agentic=18)
LLM-Läufe: 32   Nicht-LLM: 4 (12-fast:no_signal, 12-agentic:no_signal, 13-fast:no_signal, 13-agentic:no_signal)

[1-3] TREFFERQUOTE
  gesamt  : 30/36 = 83.3333%  → 83%   (falsch: ['01','02','04','05'])   OK
  fast    : 14/18 = 77.7778%  → 78%   (falsch: ['01','02','04','05'])   OK
  agentic : 16/18 = 88.8889%  → 89%   (falsch: ['01','05'])             OK

[4] HALLUZINATIONEN
  Überhöhungsversuche: 05-fast(0/3→1), 15-fast(0/3→1), 16-fast(0/3→1)   = 3   OK
  durchgekommen (final>=3 oder match): 0                                       OK

[5] CLAMP-EINGRIFFE
  runter (4): 05-fast(3→1), 09-fast(2→1), 15-fast(3→1), 16-fast(3→1)
  hoch   (5): 01-fast(1→2), 01-agentic(1→2), 02-fast(2→3), 03-fast(3→4), 04-fast(2→4)
  LLM-Läufe=32, Eingriffe=9                                                    OK

[6] MEDIAN-LAUFZEITEN
  fast    : Median(alle 18)=40.15s | Median(LLM 16)=41.55s  Spanne 31.3–892.1s  OK
  agentic : Median(alle 18)= 6.35s | Median(LLM 16)= 6.40s  Spanne  5.6–10.0s   OK

ERGEBNIS: Alle Berichtswerte aus Abschnitt 7 sind durch die Rohdaten belegt. ✅  (Exit 0)
```

Die vollständige Audit-Tabelle aller 36 Läufe druckt das Skript bei jedem Lauf mit aus.
