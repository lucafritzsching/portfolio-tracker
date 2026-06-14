"""Reproduzierbare Nachrechnung aller Kennzahlen aus Abschnitt 7 von refactor_validation.md.

Liest die Rohdaten (refactor_nl_validation_raw.json, 36 Läufe) und rechnet jede Kennzahl
unabhängig neu: Trefferquote (gesamt/fast/agentic), Halluzinationen, Clamp-Eingriffe und
Median-Laufzeiten. Druckt je Kennzahl Rohdaten-Basis, Formel und Ergebnis und prüft das
Ergebnis per assert gegen den im Bericht behaupteten Wert. Exit 0 = alle Behauptungen belegt.

Ausführen (von überall):
    python3 docs/evidence/refactor_nl_verify.py
"""
import json
import statistics
from pathlib import Path

RAW = Path(__file__).parent / "refactor_nl_validation_raw.json"
rows = json.loads(RAW.read_text())

fast = [r for r in rows if r["mode"] == "fast"]
agentic = [r for r in rows if r["mode"] == "agentic"]
llm_runs = [r for r in rows if r["source"] == "llm"]          # echte LLM-Calls
non_llm = [r for r in rows if r["source"] != "llm"]           # no_signal/fallback (kein Call)

print(f"Rohdaten : {RAW}")
print(f"Records  : {len(rows)}  (fast={len(fast)}, agentic={len(agentic)})")
print(f"LLM-Läufe: {len(llm_runs)}   Nicht-LLM: {len(non_llm)} "
      f"({', '.join(r['id'] + '-' + r['mode'] + ':' + r['source'] for r in non_llm)})")
print("=" * 78)

fails = []


def check(label, got, expected):
    ok = got == expected
    print(f"  → {label}: erhalten={got!r}  erwartet(Bericht)={expected!r}  {'OK' if ok else 'ABWEICHUNG'}")
    if not ok:
        fails.append(label)


# ── 1-3. Trefferquoten ───────────────────────────────────────────────────────
print("\n[1-3] TREFFERQUOTE  (Feld `correct`)  ·  Formel: count(correct==true) / n")
for label, rs, exp_pct in [("gesamt", rows, 83), ("fast", fast, 78), ("agentic", agentic, 89)]:
    c = sum(1 for r in rs if r["correct"] is True)
    pct = 100 * c / len(rs)
    wrong = [r["id"] for r in rs if r["correct"] is not True]
    print(f"  {label:8}: {c}/{len(rs)} = {pct:.4f}%  → gerundet {round(pct)}%   (falsch: {sorted(set(wrong))})")
    check(f"{label}-Quote", round(pct), exp_pct)

# ── 4. Halluzinationen ───────────────────────────────────────────────────────
print("\n[4] HALLUZINATIONEN  ·  Def.: Match/`final>=3` auf einer Schlagzeile mit Regex-Basis 0")
attempts = [r for r in rows if r["regex_strength"] == 0 and (r["llm_strength"] or 0) >= 3]
print("  Überhöhungsversuche (regex_strength==0 ∧ llm_strength>=3):")
for r in attempts:
    print(f"     {r['id']}-{r['mode']:7} regex=0 llm_roh={r['llm_strength']} → final={r['final']} matches={r['matches']}")
got_through = [r for r in rows if r["regex_strength"] == 0 and (r["matches"] is True or r["final"] >= 3)]
check("Überhöhungsversuche", len(attempts), 3)
check("Halluzinationen (durchgekommen)", len(got_through), 0)

# ── 5. Clamp-Eingriffe ───────────────────────────────────────────────────────
print("\n[5] CLAMP-EINGRIFFE  ·  Basis: LLM-Läufe (source=='llm')  ·  Eingriff: final != llm_strength")
clamped = [r for r in llm_runs if r["llm_strength"] is not None and r["final"] != r["llm_strength"]]
down = [r for r in clamped if r["final"] < r["llm_strength"]]
up = [r for r in clamped if r["final"] > r["llm_strength"]]
print(f"  runter ({len(down)}): " + ", ".join(f"{r['id']}-{r['mode']}({r['llm_strength']}→{r['final']})" for r in down))
print(f"  hoch   ({len(up)}): " + ", ".join(f"{r['id']}-{r['mode']}({r['llm_strength']}→{r['final']})" for r in up))
check("LLM-Läufe (Nenner)", len(llm_runs), 32)
check("Clamp-Eingriffe", len(clamped), 9)
check("davon runter", len(down), 4)
check("davon hoch", len(up), 5)

# ── 6. Median-Laufzeiten ─────────────────────────────────────────────────────
print("\n[6] MEDIAN-LAUFZEITEN  (Feld `secs`)  ·  Bericht-Basis: nur LLM-Läufe (no_signal=0,0s ausgenommen)")
print("    Hinweis: über ALLE 18 Läufe ergibt sich ein anderer Median (siehe unten).")
for mode, exp_llm in [("fast", 41.5), ("agentic", 6.4)]:
    rs = [r for r in rows if r["mode"] == mode]
    all_secs = sorted(r["secs"] for r in rs)
    llm_secs = sorted(r["secs"] for r in rs if r["source"] == "llm")
    med_all = statistics.median(all_secs)
    med_llm = statistics.median(llm_secs)
    print(f"  {mode:8}: Median(alle {len(all_secs)}) = {med_all:.2f}s   |   "
          f"Median(LLM {len(llm_secs)}) = {med_llm:.2f}s   "
          f"Spanne LLM {min(llm_secs)}–{max(llm_secs)}s")
    # Bericht rundet auf 1 Nachkommastelle; 41,55→41,5/41,6 ist im Toleranzbereich.
    ok = abs(round(med_llm, 1) - exp_llm) <= 0.1
    print(f"  → Median-{mode} (LLM-Basis): {med_llm:.2f}s  erwartet(Bericht)≈{exp_llm}s  "
          f"{'OK' if ok else 'ABWEICHUNG'}")
    if not ok:
        fails.append(f"Median-{mode}")

# ── Audit-Tabelle (vollständige Nachvollziehbarkeit) ─────────────────────────
print("\n" + "=" * 78)
print("AUDIT-TABELLE (alle 36 Läufe)")
print(f"{'id':>2} {'mode':7} {'regex':>5} {'llmroh':>6} {'final':>5} {'match':>5} {'src':14} "
      f"{'corr':>4} {'secs':>7}")
for r in rows:
    print(f"{r['id']:>2} {r['mode']:7} {r['regex_strength']:>5} {str(r['llm_strength']):>6} "
          f"{r['final']:>5} {str(r['matches']):>5} {r['source']:14} "
          f"{'OK' if r['correct'] else 'XX':>4} {r['secs']:>7}")

print("\n" + "=" * 78)
if fails:
    print(f"ERGEBNIS: {len(fails)} ABWEICHUNG(EN): {fails}")
    raise SystemExit(1)
print("ERGEBNIS: Alle Berichtswerte aus Abschnitt 7 sind durch die Rohdaten belegt. ✅")
