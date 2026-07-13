"""Determinismus-vs-LLM-Achsen aus den vorhandenen 36-Fälle-Rohdaten ableiten (read-only).

Beantwortet zwei Teilfragen der Forschungsfrage ohne Re-Run:
  (A) Tool-Calling-Agent (agentic) vs. ein einzelner LLM-Call (fast) — Trefferquote.
  (B) Geführt (regex-Clamp) vs. pures LLM (ohne Clamp) — Trefferquote + False-Positives.

Quelle: refactor_nl_validation_raw.json (Felder exp_match=Ground-Truth, matches=final nach Clamp,
llm_strength=LLM-Rohstärke vor Clamp, correct=final==exp). „pures LLM"-Entscheidung ist ein PROXY:
matches := llm_strength >= 3 (das LLM wollte einen qualifizierenden Katalysator) — der rohe
llm.matches-Bool wird nicht gespeichert. Hinweis: Daten stammen von VOR dem think:false-Fix.

Lauf (Repo-Root):  python3 docs/evidence/axes_analysis.py
"""
import json
from pathlib import Path

rows = json.loads((Path(__file__).parent / "refactor_nl_validation_raw.json").read_text())


def quote(rs):
    c = sum(1 for r in rs if r["correct"] is True)
    return c, len(rs), round(100 * c / len(rs))


print("=== (A) 1-Call (fast) vs. Tool-Agent (agentic) ===")
for lbl in ("fast", "agentic"):
    c, n, p = quote([r for r in rows if r["mode"] == lbl])
    print(f"  {lbl:8} Trefferquote {c}/{n} = {p}%")

print("\n=== (B) geführt (Clamp) vs. pures LLM (ohne Clamp) — nur LLM-Läufe ===")
llm = [r for r in rows if r["source"] == "llm"]
g_corr = p_corr = g_fp = p_fp = 0
suppressed = []  # Clamp unterdrückt korrektes LLM-Urteil (regex-Rubrik unvollständig)
for r in llm:
    exp = r["exp_match"]
    g_m = r["matches"]                       # final, nach Clamp
    p_m = (r["llm_strength"] or 0) >= 3       # Proxy: ohne Clamp
    g_corr += g_m == exp; p_corr += p_m == exp
    g_fp += g_m and not exp; p_fp += p_m and not exp
    if p_m == exp and g_m != exp:
        suppressed.append(r["id"] + "-" + r["mode"])
n = len(llm)
print(f"  LLM-Läufe: {n}")
print(f"  geführt (final):  {g_corr}/{n} = {round(100*g_corr/n)}%   False-Positives: {g_fp}")
print(f"  pur  (Proxy):     {p_corr}/{n} = {round(100*p_corr/n)}%   False-Positives: {p_fp}")
print(f"  Clamp blockt {p_fp - g_fp} False-Positive(s); Kosten: unterdrückte korrekte Urteile = {suppressed}")

print("\n=== Halluzinations-Guard (regex_strength==0 ∧ llm_strength>=3) ===")
att = [r for r in rows if r["regex_strength"] == 0 and (r["llm_strength"] or 0) >= 3]
through = [r for r in rows if r["regex_strength"] == 0 and (r["matches"] is True or r["final"] >= 3)]
print(f"  Überhöhungsversuche des LLM: {len(att)}  →  durchgekommen: {len(through)}")
for r in att:
    print(f"    {r['id']}-{r['mode']}: regex=0 llm_roh={r['llm_strength']} → final={r['final']} "
          f"matches={r['matches']} (Ground-Truth exp={r['exp_match']})")
