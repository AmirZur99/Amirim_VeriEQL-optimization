import json, re, importlib.util, os

_spec = importlib.util.spec_from_file_location("sa", os.path.join("parsers","semantics_analyzer.py"))
_mod = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_mod)
SA = _mod.SemanticsAnalyzer

EXCLUDE_RE = [re.compile(p) for p in [
    r"\bNOT\s+IN\b", r"\bNOT\s+EXISTS\b", r"\bGROUP\s+BY\b", r"\bHAVING\b",
    r"\bCOUNT\s*\(", r"\bSUM\s*\(", r"\bAVG\s*\(", r"\bMAX\s*\(", r"\bMIN\s*\(",
    r"\bUNION\b", r"\bINTERSECT\b", r"\bEXCEPT\b",
]]
WANT_RE = [re.compile(p) for p in [r"\bEXISTS\b", r"\bIN\s*\(", r"\bANY\b", r"\bSOME\b"]]

def scoped(q1, q2):
    for q in (q1, q2):
        if any(r.search(q.upper()) for r in EXCLUDE_RE):
            return False
    return True

def wanted(q1, q2):
    for q in (q1, q2):
        if any(r.search(q.upper()) for r in WANT_RE):
            return True
    return False

DATASETS = [
    ("literature", "benchmarks/literature/literature.jsonlines", "experiments/2025_10_31/literature.out", "pos"),
    ("calcite",    "benchmarks/calcite/calcite2.jsonlines",      "experiments/2025_10_31/calcite.out",    "pos"),
    ("leetcode",   "benchmarks/leetcode/leetcode.jsonlines",     "experiments/2025_10_31/leetcode.out",   "pair"),
]

n = 0
for label, bp, op, strat in DATASETS:
    bench = [json.loads(l) for l in open(bp, encoding="utf-8") if l.strip()]
    out   = [json.loads(l) for l in open(op, encoding="utf-8") if l.strip()]
    pmap  = {(o["pair"][0], o["pair"][1]): o for o in out} if strat == "pair" else {}

    for i, b in enumerate(bench):
        q1, q2 = b["pair"]
        if not scoped(q1, q2) or not wanted(q1, q2):
            continue
        o = out[i] if strat == "pos" else pmap.get((q1, q2))
        if not o:
            continue
        states = o.get("states", [])
        if "NEQ" in states or not states or states[-1] != "TMO":
            continue
        try:
            sa = SA(b["schema"])
            v  = sa.fast_path_equivalence_check(q1, q2, b["constraint"])
            c1 = sa.count_bag_variables_filtered(q1, b["constraint"])
            c2 = sa.count_bag_variables_filtered(q2, b["constraint"])
            m1 = sa.analyze_with_key_filter(q1, b["constraint"])
            m2 = sa.analyze_with_key_filter(q2, b["constraint"])
        except:
            continue
        if v != "NOT_EQUIVALENT":
            continue

        n += 1
        print(f"=== FALSE NEGATIVE #{n}  [{label}] ===")
        print(f"  c1={c1}  c2={c2}  EQU-states-before-TMO={len(states)-1}")
        print(f"  Schema     : {b['schema']}")
        print(f"  Constraints: {b['constraint']}")
        print(f"  Q1 BAG map : {m1}")
        print(f"  Q2 BAG map : {m2}")
        # Which WANT pattern matched
        matched = [p.pattern for p in WANT_RE if p.search(q1.upper()) or p.search(q2.upper())]
        print(f"  Matched EXISTS/IN/ANY pattern: {matched}")
        print(f"  Q1: {q1}")
        print(f"  Q2: {q2[:200]}")
        print()
