"""Refactor-Validierung: NL-Target-Evaluator (Alt-B Schicht 4) gegen echtes qwen3:14b.

Jeder Fall: ein selbsterklärendes, kategorie-eindeutiges Headline-Set + Freitext-Kriterium,
ausgeführt in fast UND agentic. Erfasst: regex_strength (deterministische Basis),
llm_strength (LLM-Rohstärke vor Clamp), final (nach Clamp ±1), matches, source, evidence, Dauer.
Texte: real/verbatim aus den Juni-/April-Läufen, wo die Kategorie aus der Headline allein eindeutig
ist; sonst realistisch konstruiert (im Bericht als solche gekennzeichnet). Read-only ggü. der App.
"""
import asyncio, json, time, sys
from pathlib import Path

sys.path.insert(0, "/Users/minh/IdeaProjects/portfolio-tracker/backend")
from services.nl_target import NLItem, evaluate_nl_target  # noqa: E402

EV = Path("/Users/minh/IdeaProjects/portfolio-tracker/docs/evidence")
TURN = "aktuelle Turnaround-Story"

# id, kategorie, ticker, kriterium, herkunft, [headlines], erwartet_match (ground truth), notiz
def C(cid, kat, ticker, krit, herkunft, items, exp, note):
    return dict(id=cid, kat=kat, ticker=ticker, krit=krit, herkunft=herkunft, items=items, exp=exp, note=note)

CASES = [
    C("01","klar positiv","BIOA",TURN,"real (Apr, BioAge)",
      ["BioAge Reports Positive Phase 1 Data for BGE-102 Showing Up To 86% hsCRP Reduction"], True,
      "Regex st3 → Clamp 2-4; korrekter Katalysator → Match erwartet"),
    C("02","klar positiv","CTMX",TURN,"real (Jun, CytomX)",
      ["CytomX Expands Collaboration and Licensing Agreement With Regeneron"], True,
      "Regex st4 (Lizenzdeal) → Match erwartet"),
    C("03","klar positiv","—",TURN,"konstruiert",
      ["Acme Therapeutics Announces Positive Phase 3 Topline Results Meeting the Primary Endpoint"], True,
      "Regex st5 → Clamp 4-5 → Match erwartet"),
    C("04","klar positiv","—",TURN,"konstruiert",
      ["Beta Pharma Receives FDA Approval for Lead Drug in Rare Disease"], True,
      "Regex st5 (Zulassung) → Match erwartet"),
    C("05","regex-grenze","CABA",TURN,"real (Jun, Cabaletta)",
      ["Cabaletta Bio Announces New Positive Clinical Data Supporting Rese-Cel as Potential Treatment"], True,
      "Ground truth positiv, ABER Regex st0 (kein Keyword) → Clamp 0-1 → erwartet FALSE-NEGATIV (Grenze)"),
    C("06","konferenz","ABCL",TURN,"real (Jun, AbCellera)",
      ["AbCellera Biologics Presents at Jefferies Global Healthcare Conference 2026"], False,
      "Konferenz st2 → Regex-Basis 0 → Clamp 0-1 → kein Match (Anti-Halluzination)"),
    C("07","konferenz","ADPT",TURN,"real (Jun, Adaptive)",
      ["Adaptive Biotechnologies Presents at 46th Annual William Blair Growth Stock Conference"], False,
      "Konferenz st2 → kein Match"),
    C("08","konferenz","ASMB",TURN,"real (Jun, Assembly)",
      ["Assembly Biosciences Presents at Goldman Sachs 47th Annual Global Healthcare Conference"], False,
      "Konferenz st2 → kein Match"),
    C("09","analyst","ALKS",TURN,"real (Jun, Alkermes)",
      ["RBC Capital Maintains Outperform on Alkermes, Raises Price Target to $56"], False,
      "Analyst-PT st2 → Regex-Basis 0 → kein Match"),
    C("10","analyst","ABSI",TURN,"real (Jun, Absci)",
      ["Leerink Partners Initiates Coverage on Absci With Outperform Rating"], False,
      "Analyst-Initiation → kein Match"),
    C("11","analyst","ARVN",TURN,"real (Jun, Arvinas)",
      ["Stephens & Co. Reiterates Overweight on Arvinas, Maintains $18 Price Target"], False,
      "Analyst-Reiterate st2 → kein Match"),
    C("12","negativ","—",TURN,"konstruiert",
      ["Gamma Therapeutics Announces Phase 3 Trial Failed to Meet Primary Endpoint"], False,
      "negativ → Prefilter droppt → no_signal, kein LLM-Call"),
    C("13","negativ","—",TURN,"konstruiert",
      ["Delta Bio Halts Lead Program After FDA Places Clinical Hold"], False,
      "negativ → no_signal"),
    C("14","insider-only","—",TURN,"konstruiert (Form-4-Stil)",
      ["Acme Therapeutics Director Reports Open-Market Purchase of 100,000 Shares (Form 4)"], False,
      "Insider-Kauf ist kein News-Katalysator → Regex-Basis 0 → kein Match (Grenze des NL-Agenten)"),
    C("15","insider-only","—",TURN,"konstruiert (Form-4-Stil)",
      ["Beta Bio CEO Buys $2 Million of Company Stock in Open-Market Transaction"], False,
      "Insider-Kauf → kein News-Turnaround → kein Match"),
    C("16","schwach-mix","ABSI",TURN,"real (Jun, Absci, 2 Headlines)",
      ["Absci Corporation Presents at Jefferies Global Healthcare Conference 2026",
       "Leerink Partners Initiates Coverage on Absci With Outperform Rating"], False,
      "Konferenz + Analyst, beide st2 → Regex-Basis 0 → kein Match"),
    C("17","mix pos+neg","—",TURN,"konstruiert (2 Headlines)",
      ["Epsilon Pharma Announces Positive Phase 2 Data in Lupus",
       "Epsilon Pharma Faces Securities Class Action Lawsuit Over Disclosures"], True,
      "Prefilter droppt das Negative, beurteilt das Positive (st4) → Match erwartet"),
    C("18","anderes Ziel","CTMX","hat eine neue Partnerschaft oder einen Lizenzdeal abgeschlossen","real (Jun, CytomX)",
      ["CytomX Expands Collaboration and Licensing Agreement With Regeneron"], True,
      "Konfigurierbares Ziel (ADR-14): Kriterium=Partnerschaft, Lizenzdeal-Headline → Match"),
]


async def run_case(case, mode, cache):
    items = [NLItem(text=t) for t in case["items"]]
    t0 = time.time()
    v = await evaluate_nl_target(case["krit"], items, ticker="", name="", mode=mode, cache=cache)
    dt = time.time() - t0
    return dict(
        id=case["id"], kat=case["kat"], ticker=case["ticker"], krit=case["krit"],
        herkunft=case["herkunft"], mode=mode, headlines=case["items"],
        regex_strength=v.regex_strength, llm_strength=v.llm_strength, final=v.strength,
        matches=v.matches, source=v.source, evidence=v.evidence, reason=v.reason,
        exp_match=case["exp"], exp_note=case["note"], correct=(v.matches == case["exp"]), secs=round(dt, 1),
    )


async def main():
    cache, out = {}, []
    for case in CASES:
        for mode in ("fast", "agentic"):
            r = await run_case(case, mode, cache)
            out.append(r)
            print(f"[{r['id']}/{mode:7}] {r['kat']:13} regex={r['regex_strength']} "
                  f"llm_raw={str(r['llm_strength']):>4} final={r['final']} match={str(r['matches']):>5} "
                  f"src={r['source']:14} exp={str(r['exp_match']):>5} {'OK' if r['correct'] else 'XX'} {r['secs']}s",
                  flush=True)
    (EV / "refactor_nl_validation_raw.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    n_ok = sum(1 for r in out if r["correct"])
    print(f"\nDONE {n_ok}/{len(out)} == ground truth. JSON geschrieben.", flush=True)


asyncio.run(main())
