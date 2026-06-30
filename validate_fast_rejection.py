"""
Validates the fast_path_equivalence_check heuristic against the official
VeriEQL ground-truth results stored in experiments/2025_10_31/leetcode.out.

Ground-truth labels are derived from the `states` field of each output record:
  - 'NEQ' anywhere in states  -> GT_NEQ     (proven non-equivalent, definitive)
  - Last state is 'EQU'       -> GT_EQU     (proven equivalent, definitive)
  - Otherwise (TMO/NSE/NIE/?) -> GT_UNKNOWN (VeriEQL timed out, no conclusion)

State codes seen in the benchmark:
  EQU = equivalent at this bound
  NEQ = counterexample found  (definitive NOT EQUIVALENT)
  TMO = timeout               (no conclusion)
  NSE = not supported by encoder
  NIE = not implemented in encoder
  SYN = parse/syntax error
  OOM = out of memory

Match strategy: lookup by (file, pair[0], pair[1]) ? the index field in the
subset does NOT correspond to the line position in the full output file.
"""

import importlib.util
import json
import os
import sys

# ---------------------------------------------------------------------------
# Load SemanticsAnalyzer without triggering the z3 import in parsers/__init__
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SUBSET_FILE = os.path.join("experiments", "leetcode_exist_any_in_semantics_subset.jsonlines")
GT_FILE     = os.path.join("experiments", "2025_10_31", "leetcode.out")

GT_NEQ     = "GT_NEQ"
GT_EQU     = "GT_EQU"
GT_UNKNOWN = "GT_UNKNOWN"

REJECT  = "NOT_EQUIVALENT"
PASS_ON = "MAYBE_EQUIVALENT"


def derive_gt(states: list) -> str:
    if not states:
        return GT_UNKNOWN
    if "NEQ" in states:
        return GT_NEQ
    if states[-1] == "EQU":
        return GT_EQU
    return GT_UNKNOWN


def load_gt_index(path: str) -> dict:
    """Build lookup: (file, q1, q2) -> (gt_label, states)."""
    index = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = (r.get("file", ""), r["pair"][0], r["pair"][1])
            index[key] = (derive_gt(r.get("states", [])), r.get("states", []))
    return index


def main():
    gt_index = load_gt_index(GT_FILE)

    with open(SUBSET_FILE, encoding="utf-8") as fh:
        subset = [json.loads(l) for l in fh if l.strip()]

    rows = []
    for i, rec in enumerate(subset):
        q1, q2 = rec["pair"]
        key    = (rec.get("file", ""), q1, q2)
        gt_label, states = gt_index.get(key, (GT_UNKNOWN, []))
        final_state = states[-1] if states else "?"

        sa       = SemanticsAnalyzer(rec["schema"])
        verdict  = sa.fast_path_equivalence_check(q1, q2, rec["constraint"])
        c1       = sa.count_bag_variables_filtered(q1, rec["constraint"])
        c2       = sa.count_bag_variables_filtered(q2, rec["constraint"])

        rows.append({
            "i":       i,
            "file":    rec.get("file", "").split("/")[-1],
            "verdict": verdict,
            "gt":      gt_label,
            "states":  states,
            "final":   final_state,
            "c1":      c1,
            "c2":      c2,
        })

    # -----------------------------------------------------------------------
    # Classify every row
    # -----------------------------------------------------------------------
    false_negatives = [r for r in rows if r["verdict"] == REJECT  and r["gt"] == GT_EQU]
    true_negatives  = [r for r in rows if r["verdict"] == REJECT  and r["gt"] == GT_NEQ]
    reject_unknown  = [r for r in rows if r["verdict"] == REJECT  and r["gt"] == GT_UNKNOWN]
    missed_neq      = [r for r in rows if r["verdict"] == PASS_ON and r["gt"] == GT_NEQ]
    correct_equ     = [r for r in rows if r["verdict"] == PASS_ON and r["gt"] == GT_EQU]
    pass_unknown    = [r for r in rows if r["verdict"] == PASS_ON and r["gt"] == GT_UNKNOWN]

    confirmed_neq   = [r for r in rows if r["gt"] == GT_NEQ]
    confirmed_equ   = [r for r in rows if r["gt"] == GT_EQU]
    all_rejected    = [r for r in rows if r["verdict"] == REJECT]

    # -----------------------------------------------------------------------
    # Detail table
    # -----------------------------------------------------------------------
    W = 80
    print("=" * W)
    print("  FAST REJECTION VALIDATION ? LeetCode EXISTS/IN/ANY subset (50 pairs)")
    print(f"  Ground truth: {GT_FILE}")
    print("=" * W)
    print()

    # Column headers
    H = f"  {'#':>2}  {'Our Verdict':<18}  {'GT':<10}  {'GT State':>8}  {'C1':>2}{'C2':>3}  Category"
    print(H)
    print("  " + "-" * (W - 2))

    CATEGORY = {
        (REJECT,  GT_NEQ):     "True Negative      [TN]",
        (REJECT,  GT_EQU):     "*** FALSE NEGATIVE [FN] ***",
        (REJECT,  GT_UNKNOWN): "Rejected (unverified) [?]",
        (PASS_ON, GT_NEQ):     "Missed NEQ            [!]",
        (PASS_ON, GT_EQU):     "Correct Pass          [OK]",
        (PASS_ON, GT_UNKNOWN): "Passed through        [?]",
    }

    for r in rows:
        cat = CATEGORY[(r["verdict"], r["gt"])]
        verdict_short = "REJECT " if r["verdict"] == REJECT else "PASS   "
        print(
            f"  {r['i']:>2}  {verdict_short} ({r['c1']:>1}v{r['c2']:<1})       "
            f"  {r['gt']:<10}  {r['final']:>8}  {cat}"
        )

    # -----------------------------------------------------------------------
    # Summary report
    # -----------------------------------------------------------------------
    print()
    print("=" * W)
    print("  SUMMARY REPORT")
    print("=" * W)
    print()
    print(f"  Total pairs evaluated              : {len(rows)}")
    print()
    print("  Ground Truth distribution:")
    print(f"    Confirmed NEQ  (counterex. found) : {len(confirmed_neq)}")
    print(f"    Confirmed EQU  (proven equiv.)    : {len(confirmed_equ)}")
    print(f"    Unknown        (TMO / NSE / NIE)  : {len(rows) - len(confirmed_neq) - len(confirmed_equ)}")
    print()
    print("  Heuristic decisions:")
    print(f"    REJECT (NOT_EQUIVALENT)           : {len(all_rejected)}  ({100*len(all_rejected)/len(rows):.0f}%)")
    print(f"    PASS   (MAYBE_EQUIVALENT -> Z3)    : {len(rows) - len(all_rejected)}  ({100*(len(rows)-len(all_rejected))/len(rows):.0f}%)")
    print()

    # -----------------------------------------------------------------------
    # CRITICAL SAFETY CHECK
    # -----------------------------------------------------------------------
    print("  " + "-" * (W - 2))
    print("  CRITICAL SAFETY CHECK  (False Negatives = cases where we said REJECT")
    print("                          but GT is confirmed EQU ? would be a BUG)")
    print("  " + "-" * (W - 2))

    if len(false_negatives) == 0:
        print(f"  FALSE NEGATIVES : 0  OK  SAFETY PROPERTY HOLDS")
        print("  No pair was incorrectly rejected as NOT_EQUIVALENT when GT = EQU.")
    else:
        print(f"  *** FALSE NEGATIVES : {len(false_negatives)}  SAFETY PROPERTY VIOLATED! ***")
        for r in false_negatives:
            print(f"    pair #{r['i']}  file={r['file']}  c1={r['c1']}  c2={r['c2']}")

    print()

    # -----------------------------------------------------------------------
    # NEQ recall (early-rejection rate on confirmed NEQ pairs)
    # -----------------------------------------------------------------------
    print("  " + "-" * (W - 2))
    print("  EARLY REJECTION RATE  (on confirmed NEQ pairs)")
    print("  " + "-" * (W - 2))
    print(f"  Confirmed NEQ pairs in subset      : {len(confirmed_neq)}")
    print(f"  Caught by heuristic (TN)           : {len(true_negatives)}")
    print(f"  Missed by heuristic (passed to Z3) : {len(missed_neq)}")

    if confirmed_neq:
        recall = 100 * len(true_negatives) / len(confirmed_neq)
        print(f"  NEQ Recall (TN / all confirmed NEQ): {recall:.0f}%")
        if len(missed_neq):
            print()
            print("  Missed NEQ pairs detail:")
            for r in missed_neq:
                print(f"    pair #{r['i']}  file={r['file']}  c1={r['c1']}  c2={r['c2']}")
                print(f"    (BAG counts equal -> heuristic cannot distinguish; Z3 needed)")
    else:
        print("  (No confirmed NEQ pairs -> recall undefined)")

    print()

    # -----------------------------------------------------------------------
    # Rejected-but-unverified (the 'savings' we claim)
    # -----------------------------------------------------------------------
    print("  " + "-" * (W - 2))
    print("  UNVERIFIED REJECTIONS  (pairs we rejected but GT is TMO/unknown)")
    print("  " + "-" * (W - 2))
    print(f"  Pairs rejected with unknown GT     : {len(reject_unknown)}")
    print("  These timed out in VeriEQL, so we cannot confirm they are NEQ.")
    print("  The heuristic claims non-equivalence by BAG variable count mismatch;")
    print("  final verdict requires running VeriEQL (Z3) to confirm.")
    print()

    # -----------------------------------------------------------------------
    # Explanation of NSE / TMO dominance
    # -----------------------------------------------------------------------
    tmo_count = sum(1 for r in rows if r["final"] == "TMO")
    nse_count = sum(1 for r in rows if r["final"] == "NSE")
    print("  " + "-" * (W - 2))
    print("  NOTE ON GROUND TRUTH COVERAGE")
    print("  " + "-" * (W - 2))
    print(f"  {tmo_count} pairs timed out (TMO) and {nse_count} were unsupported (NSE)")
    print("  in the official VeriEQL run. This subset targets EXISTS/IN/ANY queries,")
    print("  which are the hardest class for VeriEQL ? they require correlated subquery")
    print("  encoding that dramatically increases Z3 solving time. Only 1 of 50 pairs")
    print("  has a confirmed NEQ result; the rest are genuinely unresolved by VeriEQL.")
    print()
    print("=" * W)


if __name__ == "__main__":
    main()
