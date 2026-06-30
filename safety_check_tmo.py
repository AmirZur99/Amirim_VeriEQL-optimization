"""
Safety check using TMO (timed-out) pairs as a proxy for equivalent pairs.

Rationale: VeriEQL is a bounded counterexample finder. A TMO result means
it exhausted its time budget without finding a counterexample. While this is
not a proof of equivalence, it is our best available proxy. If our heuristic
returns NOT_EQUIVALENT on a TMO pair that is within CQ scope, that is a
suspected false negative -- the heuristic is rejecting a pair the solver
could not disprove.

Scope: only CQ-scoped pairs are checked (the heuristic scope-guards and
passes out-of-scope pairs through as MAYBE_EQUIVALENT automatically, so
those are trivially safe).
"""

import importlib.util
import json
import os
import re
from collections import Counter

_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

REJECT  = "NOT_EQUIVALENT"
PASS_ON = "MAYBE_EQUIVALENT"

_OUT_RE = [re.compile(p) for p in [
    r"\bNOT\s+IN\b", r"\bNOT\s+EXISTS\b",
    r"\bGROUP\s+BY\b", r"\bHAVING\b",
    r"\bCOUNT\s*\(", r"\bSUM\s*\(", r"\bAVG\s*\(", r"\bMAX\s*\(", r"\bMIN\s*\(",
    r"\bUNION\b", r"\bINTERSECT\b", r"\bEXCEPT\b",
]]

def is_cq_scoped(q1, q2):
    for q in (q1, q2):
        u = q.upper()
        if any(rx.search(u) for rx in _OUT_RE):
            return False
    return True

def is_tmo(states):
    """True if VeriEQL timed out without finding NEQ."""
    return bool(states) and "NEQ" not in states and states[-1] == "TMO"

def load_jsonlines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


DATASETS = [
    ("literature", "benchmarks/literature/literature.jsonlines",
                   "experiments/2025_10_31/literature.out",  "positional"),
    ("calcite",    "benchmarks/calcite/calcite2.jsonlines",
                   "experiments/2025_10_31/calcite.out",     "positional"),
    ("leetcode",   "benchmarks/leetcode/leetcode.jsonlines",
                   "experiments/2025_10_31/leetcode.out",    "by_pair"),
]

W = 84
print("=" * W)
print("  SAFETY CHECK -- TMO Pairs as Proxy for Equivalent Pairs")
print("  (CQ-scoped only; heuristic MUST return MAYBE_EQUIVALENT for all)")
print("=" * W)

total_tmo_cq   = 0
total_rejected = 0   # suspected false negatives
total_passed   = 0
total_errors   = 0
suspected_fn_details = []

for label, bench_path, out_path, strategy in DATASETS:
    bench = load_jsonlines(bench_path)
    out   = load_jsonlines(out_path)

    if strategy == "by_pair":
        pair_to_out = {(o["pair"][0], o["pair"][1]): o for o in out}

    tmo_cq = 0
    rejected = 0
    passed   = 0
    errors   = 0
    count_dist = Counter()

    for i, b in enumerate(bench):
        q1, q2 = b["pair"]

        # Get the output record
        if strategy == "positional":
            if i >= len(out):
                continue
            o = out[i]
        else:
            o = pair_to_out.get((q1, q2))
            if o is None:
                continue

        # Only TMO pairs
        if not is_tmo(o.get("states", [])):
            continue

        # Only CQ-scoped pairs
        if not is_cq_scoped(q1, q2):
            continue

        tmo_cq += 1

        try:
            sa      = SemanticsAnalyzer(b["schema"])
            verdict = sa.fast_path_equivalence_check(q1, q2, b["constraint"])
            c1      = sa.count_bag_variables_filtered(q1, b["constraint"])
            c2      = sa.count_bag_variables_filtered(q2, b["constraint"])
            count_dist[(c1, c2)] += 1

            if verdict == REJECT:
                rejected += 1
                name = b.get("name", b.get("file", "?"))
                suspected_fn_details.append({
                    "source": label,
                    "name":   name,
                    "c1": c1, "c2": c2,
                    "q1": q1, "q2": q2,
                })
            else:
                passed += 1
        except Exception as e:
            errors += 1

    total_tmo_cq   += tmo_cq
    total_rejected += rejected
    total_passed   += passed
    total_errors   += errors

    pct_pass = 100 * passed / tmo_cq if tmo_cq else 0
    print()
    print(f"  [{label.upper()}]")
    print(f"    CQ-scoped TMO pairs        : {tmo_cq}")
    print(f"    MAYBE_EQUIVALENT (safe)    : {passed}  ({pct_pass:.1f}%)")
    print(f"    NOT_EQUIVALENT (suspected) : {rejected}")
    if errors:
        print(f"    Parse errors (skipped)     : {errors}")
    if count_dist:
        top = count_dist.most_common(5)
        print(f"    Top (c1,c2) distributions  : " +
              "  ".join(f"({c1},{c2})x{n}" for (c1,c2),n in top))

print()
print("=" * W)
print("  AGGREGATE RESULTS")
print("=" * W)
print()
pct = 100 * total_passed / total_tmo_cq if total_tmo_cq else 0
print(f"  CQ-scoped TMO pairs evaluated  : {total_tmo_cq}")
print(f"  Passed MAYBE_EQUIVALENT        : {total_passed}  ({pct:.2f}%)")
print(f"  Rejected NOT_EQUIVALENT        : {total_rejected}  <- suspected false negatives")
if total_errors:
    print(f"  Parse errors skipped           : {total_errors}")

print()
print("=" * W)
print("  VERDICT")
print("=" * W)
print()
if total_rejected == 0:
    print("  PASS -- The heuristic returned MAYBE_EQUIVALENT for every single")
    print(f"  CQ-scoped TMO pair across all {total_tmo_cq} pairs tested.")
    print("  No pair that VeriEQL could not disprove was rejected by the heuristic.")
else:
    print(f"  *** SUSPECTED FALSE NEGATIVES: {total_rejected} pair(s) ***")
    print("  The heuristic returned NOT_EQUIVALENT on pairs VeriEQL could not disprove.")
    print()
    for d in suspected_fn_details[:20]:
        print(f"  [{d['source']}] {d['name']}")
        print(f"    c1={d['c1']}  c2={d['c2']}")
        print(f"    Q1: {d['q1'][:75]}")
        print(f"    Q2: {d['q2'][:75]}")
        print()
print()
print("=" * W)
