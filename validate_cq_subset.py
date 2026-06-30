"""
Validates fast_path_equivalence_check on the CQ-scoped LeetCode subset
(positive EXISTS/IN only -- no NOT IN, NOT EXISTS, aggregation, or set ops).

Ground truth from: experiments/2025_10_31/leetcode.out
Subset:            experiments/leetcode_cq_positive_subset.jsonlines
"""

import importlib.util
import json
import os
import sys

# Load SemanticsAnalyzer directly to avoid the z3 import in parsers/__init__
_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

SUBSET_FILE = os.path.join("experiments", "leetcode_cq_positive_subset.jsonlines")
GT_FILE     = os.path.join("experiments", "2025_10_31", "leetcode.out")

GT_NEQ  = "GT_NEQ"
GT_EQU  = "GT_EQU"
GT_UNKN = "GT_UNKN"

REJECT  = "NOT_EQUIVALENT"
PASS_ON = "MAYBE_EQUIVALENT"


def derive_gt(states):
    if not states:
        return GT_UNKN
    if "NEQ" in states:
        return GT_NEQ
    if states[-1] == "EQU":
        return GT_EQU
    return GT_UNKN


def build_gt_index(path):
    idx = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = (r.get("file", ""), r["pair"][0], r["pair"][1])
            idx[key] = (derive_gt(r.get("states", [])), r.get("states", []))
    return idx


def main():
    gt_index = build_gt_index(GT_FILE)

    with open(SUBSET_FILE, encoding="utf-8") as fh:
        subset = [json.loads(l) for l in fh if l.strip()]

    rows = []
    parse_errors = []

    for i, rec in enumerate(subset):
        q1, q2 = rec["pair"]
        src = rec.get("file", "").split("/")[-1]
        key = (rec.get("file", ""), q1, q2)
        gt_label, states = gt_index.get(key, (GT_UNKN, []))
        final_state = states[-1] if states else "?"

        try:
            sa      = SemanticsAnalyzer(rec["schema"])
            verdict = sa.fast_path_equivalence_check(q1, q2, rec["constraint"])
            c1      = sa.count_bag_variables_filtered(q1, rec["constraint"])
            c2      = sa.count_bag_variables_filtered(q2, rec["constraint"])
        except Exception as e:
            parse_errors.append((i, src, str(e)[:80]))
            continue

        rows.append({
            "i":      i,
            "src":    src,
            "verdict": verdict,
            "gt":     gt_label,
            "final":  final_state,
            "c1":     c1,
            "c2":     c2,
        })

    # Classify
    false_negatives = [r for r in rows if r["verdict"] == REJECT  and r["gt"] == GT_EQU]
    true_negatives  = [r for r in rows if r["verdict"] == REJECT  and r["gt"] == GT_NEQ]
    reject_unkn     = [r for r in rows if r["verdict"] == REJECT  and r["gt"] == GT_UNKN]
    missed_neq      = [r for r in rows if r["verdict"] == PASS_ON and r["gt"] == GT_NEQ]
    correct_equ     = [r for r in rows if r["verdict"] == PASS_ON and r["gt"] == GT_EQU]
    pass_unkn       = [r for r in rows if r["verdict"] == PASS_ON and r["gt"] == GT_UNKN]

    all_rejected    = [r for r in rows if r["verdict"] == REJECT]
    confirmed_neq   = [r for r in rows if r["gt"] == GT_NEQ]
    confirmed_equ   = [r for r in rows if r["gt"] == GT_EQU]

    W = 80
    print("=" * W)
    print("  FAST REJECTION VALIDATION -- CQ Positive-EXISTS/IN LeetCode subset")
    print(f"  Ground truth: {GT_FILE}")
    print("=" * W)
    print()
    print(f"  {'#':>2}  {'Verdict':<22}  {'GT':<9}  {'State':>5}  Category")
    print("  " + "-" * (W - 2))

    CATEGORY = {
        (REJECT,  GT_NEQ):  "True Negative      [TN]",
        (REJECT,  GT_EQU):  "*** FALSE NEGATIVE [FN] ***",
        (REJECT,  GT_UNKN): "Rejected-unverified [?]",
        (PASS_ON, GT_NEQ):  "Missed NEQ          [!]",
        (PASS_ON, GT_EQU):  "Correct Pass       [OK]",
        (PASS_ON, GT_UNKN): "Passed through      [?]",
    }

    for r in rows:
        tag = f"REJECT ({r['c1']}v{r['c2']})" if r["verdict"] == REJECT else f"PASS   ({r['c1']}v{r['c2']})"
        cat = CATEGORY[(r["verdict"], r["gt"])]
        print(f"  {r['i']:>2}  {tag:<22}  {r['gt']:<9}  {r['final']:>5}  {cat}  [{r['src']}]")

    if parse_errors:
        print()
        print(f"  PARSE ERRORS ({len(parse_errors)} pairs skipped):")
        for i, src, err in parse_errors:
            print(f"    [{i:2d}] {src}: {err}")

    print()
    print("=" * W)
    print("  SUMMARY REPORT")
    print("=" * W)
    print()
    n = len(rows)
    print(f"  Pairs evaluated (excluding parse errors) : {n}  (of {len(subset)} in subset)")
    print(f"  Parse errors skipped                     : {len(parse_errors)}")
    print()
    print("  Ground Truth distribution:")
    print(f"    Confirmed NEQ (counterexample found)   : {len(confirmed_neq)}")
    print(f"    Confirmed EQU (proven equivalent)      : {len(confirmed_equ)}")
    print(f"    Unknown       (TMO / NSE / NIE)        : {n - len(confirmed_neq) - len(confirmed_equ)}")
    print()
    print("  Heuristic decisions:")
    print(f"    REJECT (NOT_EQUIVALENT)                : {len(all_rejected)}  ({100*len(all_rejected)/n:.0f}% of evaluated)")
    print(f"    PASS   (MAYBE_EQUIVALENT -> Z3)        : {n - len(all_rejected)}  ({100*(n-len(all_rejected))/n:.0f}%)")
    print()

    print("  " + "-" * (W - 2))
    print("  CRITICAL SAFETY CHECK -- False Negatives")
    print("  (We said REJECT but GT is confirmed EQU -- would be a logic bug)")
    print("  " + "-" * (W - 2))
    if not false_negatives:
        print(f"  FALSE NEGATIVES : 0  --  SAFETY PROPERTY HOLDS")
    else:
        print(f"  *** FALSE NEGATIVES : {len(false_negatives)} ***")
        for r in false_negatives:
            print(f"    pair #{r['i']}  file={r['src']}  c1={r['c1']}  c2={r['c2']}")
    print()

    print("  " + "-" * (W - 2))
    print("  EARLY REJECTION RATE  (on confirmed NEQ pairs)")
    print("  " + "-" * (W - 2))
    print(f"  Confirmed NEQ pairs : {len(confirmed_neq)}")
    print(f"  Caught early  [TN]  : {len(true_negatives)}")
    print(f"  Missed        [!]   : {len(missed_neq)}  (passed to Z3, which will find NEQ)")
    if confirmed_neq:
        recall = 100 * len(true_negatives) / len(confirmed_neq)
        print(f"  NEQ recall          : {recall:.0f}%")
    print()

    print("  " + "-" * (W - 2))
    print("  UNVERIFIED REJECTIONS (our REJECT, but VeriEQL timed out)")
    print("  " + "-" * (W - 2))
    print(f"  Rejected with unknown GT : {len(reject_unkn)}")
    print("  BAG-count mismatch detected; Z3 confirmation needed.")
    print()

    print("  " + "-" * (W - 2))
    print("  WHY ALMOST ALL GT IS UNKNOWN")
    print("  " + "-" * (W - 2))
    tmo = sum(1 for r in rows if r["final"] == "TMO")
    nse = sum(1 for r in rows if r["final"] == "NSE")
    print(f"  {tmo} pairs timed out (TMO), {nse} were unsupported (NSE) in VeriEQL.")
    print("  Correlated subquery encoding (EXISTS/IN) is the most expensive class")
    print("  for VeriEQL's Z3 backend. These pairs are genuinely hard -- which is")
    print("  exactly why a fast-rejection pre-filter has the most value here.")
    print()
    print("=" * W)


if __name__ == "__main__":
    main()
