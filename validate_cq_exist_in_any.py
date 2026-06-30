"""
Collects all CQ-scoped pairs that contain EXISTS / IN (subquery) / ANY
across all three benchmarks, cross-references with ground truth from the
2025_10_31 experiment runs, and validates fast_path_equivalence_check on them.

Inclusion criteria:
  - At least one query contains EXISTS, IN(, or ANY/SOME
  - Neither query contains out-of-scope constructs (NOT IN, NOT EXISTS,
    GROUP BY, HAVING, COUNT/SUM/AVG/MAX/MIN, UNION, INTERSECT, EXCEPT)

Ground truth derivation:
  NEQ  -> states contains "NEQ"  (definitive counterexample found)
  EQU  -> last state is "EQU", no NEQ  (proven equivalent at bound)
  TMO  -> last state is "TMO", no NEQ  (timed out, no conclusion)
  OTHER -> NSE / NIE / SYN / OOM  (not attempted or parse error)
"""

import importlib.util
import json
import os
import re
from collections import Counter, defaultdict

_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

REJECT  = "NOT_EQUIVALENT"
PASS_ON = "MAYBE_EQUIVALENT"

# ---------------------------------------------------------------------------
# Scope filter
# ---------------------------------------------------------------------------
_EXCLUDE_RE = [re.compile(p) for p in [
    r"\bNOT\s+IN\b", r"\bNOT\s+EXISTS\b",
    r"\bGROUP\s+BY\b", r"\bHAVING\b",
    r"\bCOUNT\s*\(", r"\bSUM\s*\(", r"\bAVG\s*\(", r"\bMAX\s*\(", r"\bMIN\s*\(",
    r"\bUNION\b", r"\bINTERSECT\b", r"\bEXCEPT\b",
]]
_WANT_RE = [re.compile(p) for p in [
    r"\bEXISTS\b",
    r"\bIN\s*\(",
    r"\bANY\b",
    r"\bSOME\b",
]]

def is_cq_scoped(q1, q2):
    for q in (q1, q2):
        u = q.upper()
        if any(rx.search(u) for rx in _EXCLUDE_RE):
            return False
    return True

def has_exist_in_any(q1, q2):
    for q in (q1, q2):
        u = q.upper()
        if any(rx.search(u) for rx in _WANT_RE):
            return True
    return False

# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
GT_NEQ   = "NEQ"
GT_EQU   = "EQU"
GT_TMO   = "TMO"
GT_OTHER = "OTHER"

def derive_gt(states):
    if not states:
        return GT_OTHER
    if "NEQ" in states:
        return GT_NEQ
    last = states[-1]
    if last == "EQU":
        return GT_EQU
    if last == "TMO":
        return GT_TMO
    return GT_OTHER

def load_jsonlines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
DATASETS = [
    ("literature", "benchmarks/literature/literature.jsonlines",
                   "experiments/2025_10_31/literature.out",  "positional"),
    ("calcite",    "benchmarks/calcite/calcite2.jsonlines",
                   "experiments/2025_10_31/calcite.out",     "positional"),
    ("leetcode",   "benchmarks/leetcode/leetcode.jsonlines",
                   "experiments/2025_10_31/leetcode.out",    "by_pair"),
]

# ---------------------------------------------------------------------------
# Collect subset + run heuristic
# ---------------------------------------------------------------------------
all_rows = []      # one entry per pair
parse_errors = []

for label, bench_path, out_path, strategy in DATASETS:
    bench = load_jsonlines(bench_path)
    out   = load_jsonlines(out_path)

    if strategy == "by_pair":
        pair_to_out = {(o["pair"][0], o["pair"][1]): o for o in out}

    for i, b in enumerate(bench):
        q1, q2 = b["pair"]

        if not is_cq_scoped(q1, q2):
            continue
        if not has_exist_in_any(q1, q2):
            continue

        # Ground truth
        if strategy == "positional":
            o = out[i] if i < len(out) else None
        else:
            o = pair_to_out.get((q1, q2))

        gt    = derive_gt(o.get("states", []) if o else [])
        final = (o.get("states") or ["?"])[-1] if o else "?"

        try:
            sa      = SemanticsAnalyzer(b["schema"])
            verdict = sa.fast_path_equivalence_check(q1, q2, b["constraint"])
            c1      = sa.count_bag_variables_filtered(q1, b["constraint"])
            c2      = sa.count_bag_variables_filtered(q2, b["constraint"])
        except Exception as e:
            parse_errors.append((label, b.get("name", b.get("index","?")), str(e)[:70]))
            continue

        all_rows.append({
            "source":  label,
            "name":    b.get("name", b.get("file", "?")),
            "verdict": verdict,
            "gt":      gt,
            "final":   final,
            "c1":      c1,
            "c2":      c2,
            "q1":      q1,
            "q2":      q2,
        })

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
W = 84
print("=" * W)
print("  CQ + EXISTS/IN/ANY  --  Fast Rejection Validation (all benchmarks)")
print("=" * W)
print()

sources = ["literature", "calcite", "leetcode"]

for src in sources:
    rows = [r for r in all_rows if r["source"] == src]
    if not rows:
        continue

    by_gt = defaultdict(list)
    for r in rows:
        by_gt[r["gt"]].append(r)

    rej     = [r for r in rows if r["verdict"] == REJECT]
    passed  = [r for r in rows if r["verdict"] == PASS_ON]
    fn      = [r for r in rej if r["gt"] == GT_NEQ]   # confirmed NEQ but we passed -> no, wait
    # actual FN = we REJECTED but GT says EQU
    actual_fn = [r for r in rej if r["gt"] == GT_EQU]
    tn        = [r for r in rej if r["gt"] == GT_NEQ]
    rej_tmo   = [r for r in rej if r["gt"] == GT_TMO]
    rej_other = [r for r in rej if r["gt"] == GT_OTHER]
    missed_neq = [r for r in passed if r["gt"] == GT_NEQ]

    print(f"  [{src.upper()}]  {len(rows)} CQ EXISTS/IN/ANY pairs")
    print(f"    GT breakdown:  NEQ={len(by_gt[GT_NEQ])}  EQU={len(by_gt[GT_EQU])}  "
          f"TMO={len(by_gt[GT_TMO])}  OTHER={len(by_gt[GT_OTHER])}")
    print(f"    Heuristic REJECT : {len(rej)}")
    print(f"      True Negatives   [TN]  : {len(tn)}")
    print(f"      FALSE NEGATIVES  [FN]  : {len(actual_fn)}  <-- MUST BE 0")
    print(f"      Rejected TMO     [?]   : {len(rej_tmo)}  (unverified)")
    print(f"      Rejected OTHER   [?]   : {len(rej_other)}")
    print(f"    Heuristic PASS   : {len(passed)}")
    print(f"      Missed NEQ     [!]     : {len(missed_neq)}")
    if by_gt[GT_NEQ]:
        recall = 100 * len(tn) / len(by_gt[GT_NEQ])
        print(f"    NEQ recall             : {recall:.1f}%  ({len(tn)}/{len(by_gt[GT_NEQ])})")

    # Show FN details if any
    if actual_fn:
        print(f"    *** FALSE NEGATIVE DETAILS ***")
        for r in actual_fn:
            print(f"      {r['name']}  c1={r['c1']} c2={r['c2']}")
            print(f"        Q1: {r['q1'][:75]}")
            print(f"        Q2: {r['q2'][:75]}")

    # Show TN details (small datasets)
    if tn and src != "leetcode":
        print(f"    TN details:")
        for r in tn:
            print(f"      {r['name']}  c1={r['c1']} c2={r['c2']}  GT={r['final']}")

    # Show rejected-TMO for literature (most interesting)
    if rej_tmo and src == "literature":
        print(f"    Rejected-TMO details (suspected FN):")
        for r in rej_tmo:
            print(f"      {r['name']}  c1={r['c1']} c2={r['c2']}")

    print()

# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
print("=" * W)
print("  AGGREGATE  (all benchmarks combined)")
print("=" * W)
print()

total      = len(all_rows)
all_rej    = [r for r in all_rows if r["verdict"] == REJECT]
all_pass   = [r for r in all_rows if r["verdict"] == PASS_ON]
all_neq    = [r for r in all_rows if r["gt"] == GT_NEQ]
all_equ    = [r for r in all_rows if r["gt"] == GT_EQU]
all_tmo    = [r for r in all_rows if r["gt"] == GT_TMO]
all_other  = [r for r in all_rows if r["gt"] == GT_OTHER]
fn_all     = [r for r in all_rej if r["gt"] == GT_EQU]
tn_all     = [r for r in all_rej if r["gt"] == GT_NEQ]
rej_tmo_all = [r for r in all_rej if r["gt"] == GT_TMO]
miss_neq_all = [r for r in all_pass if r["gt"] == GT_NEQ]

print(f"  Total CQ EXISTS/IN/ANY pairs : {total}  (+ {len(parse_errors)} parse errors)")
print(f"  GT distribution:")
print(f"    Confirmed NEQ : {len(all_neq)}")
print(f"    Confirmed EQU : {len(all_equ)}")
print(f"    TMO (no concl): {len(all_tmo)}")
print(f"    OTHER (NSE/NIE): {len(all_other)}")
print()
print(f"  Heuristic REJECT : {len(all_rej)}  ({100*len(all_rej)/total:.1f}%)")
print(f"    True Negatives [TN]  : {len(tn_all)}")
print(f"    FALSE NEGATIVES [FN] : {len(fn_all)}  <-- MUST BE 0")
print(f"    Rejected TMO [?]     : {len(rej_tmo_all)}")
print(f"  Heuristic PASS   : {len(all_pass)}  ({100*len(all_pass)/total:.1f}%)")
print(f"    Missed NEQ [!]       : {len(miss_neq_all)}")
print()
if all_neq:
    print(f"  NEQ Recall (TN/all confirmed NEQ) : {100*len(tn_all)/len(all_neq):.1f}%")
print()
if fn_all:
    print(f"  *** {len(fn_all)} FALSE NEGATIVE(S) DETECTED ***")
else:
    print(f"  SAFETY CHECK: 0 confirmed false negatives.")
    if rej_tmo_all:
        print(f"  Note: {len(rej_tmo_all)} rejected pairs have TMO ground truth (see safety_check_tmo.py).")

print()

# Count distribution for rejected pairs
count_dist = Counter((r["c1"], r["c2"]) for r in all_rej)
print(f"  BAG count distribution for REJECTED pairs (c1 != c2 by definition):")
for (c1, c2), n in sorted(count_dist.items(), key=lambda x: -x[1])[:10]:
    print(f"    c1={c1}  c2={c2}  -> {n} pairs")

if parse_errors:
    print()
    print(f"  Parse errors ({len(parse_errors)}):")
    for src, name, err in parse_errors[:10]:
        print(f"    [{src}] {name}: {err}")

print()
print("=" * W)
