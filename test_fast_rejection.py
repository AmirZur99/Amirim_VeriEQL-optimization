"""
Tests the fast_path_equivalence_check heuristic against VeriEQL ground-truth
results on the 50-pair LeetCode subset that contains EXISTS / IN / ANY queries.

Ground truth is taken from experiments/2025_10_31/leetcode.out, which contains
the results of running VeriEQL on the full LeetCode benchmark.

Each output record's `states` array drives the ground-truth label:
  - Contains 'NEQ'         -> GROUND_NEQ   (verifier found a counterexample)
  - All non-TMO are 'EQU', no NEQ, last is 'EQU'  -> GROUND_EQU   (proven equivalent)
  - Contains 'TMO', no NEQ -> GROUND_UNKNOWN (timed out before conclusion)

Test categories:
  True Negative  (TN) : heuristic says NOT_EQUIVALENT, ground truth is GROUND_NEQ
  False Negative (FN) : heuristic says NOT_EQUIVALENT, ground truth is GROUND_EQU  <- must be 0
  FN-Unknown         : heuristic says NOT_EQUIVALENT, ground truth is GROUND_UNKNOWN
  True Positive  (TP) : heuristic says MAYBE_EQUIVALENT, ground truth is GROUND_NEQ
  Correct Pass       : heuristic says MAYBE_EQUIVALENT, ground truth is GROUND_EQU
  Unknown Pass       : heuristic says MAYBE_EQUIVALENT, ground truth is GROUND_UNKNOWN
"""

import importlib.util
import json
import os
import sys

# ---------------------------------------------------------------------------
# Load SemanticsAnalyzer without triggering the z3 import in parsers/__init__.py
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

SUBSET_FILE  = os.path.join("experiments", "leetcode_exist_any_in_semantics_subset.jsonlines")
GROUND_TRUTH_FILE = os.path.join("experiments", "2025_10_31", "leetcode.out")

GROUND_NEQ     = "GROUND_NEQ"
GROUND_EQU     = "GROUND_EQU"
GROUND_UNKNOWN = "GROUND_UNKNOWN"


def derive_ground_truth(states: list) -> str:
    """Derive a single label from VeriEQL's per-bound states list."""
    if not states:
        return GROUND_UNKNOWN
    if "NEQ" in states:
        return GROUND_NEQ
    if states[-1] == "EQU":
        return GROUND_EQU
    return GROUND_UNKNOWN          # last state is TMO, no NEQ found


def build_ground_truth_index(gt_file: str) -> dict:
    """
    Build a lookup dict keyed by (file, q1, q2) -> ground_truth_label.
    Uses the (file, pair[0], pair[1]) tuple because the `index` field
    in the output does not match the `index` in the subset records.
    """
    index = {}
    with open(gt_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            key = (r.get("file", ""), r["pair"][0], r["pair"][1])
            index[key] = derive_ground_truth(r.get("states", []))
    return index


def main():
    # ------------------------------------------------------------------
    # Load ground truth
    # ------------------------------------------------------------------
    gt_index = build_ground_truth_index(GROUND_TRUTH_FILE)

    # ------------------------------------------------------------------
    # Load subset and run heuristic
    # ------------------------------------------------------------------
    results = []
    with open(SUBSET_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            q1, q2 = r["pair"]

            sa = SemanticsAnalyzer(r["schema"])
            heuristic = sa.fast_path_equivalence_check(q1, q2, r["constraint"])
            count1 = sa.count_bag_variables_filtered(q1, r["constraint"])
            count2 = sa.count_bag_variables_filtered(q2, r["constraint"])

            key = (r.get("file", ""), q1, q2)
            ground_truth = gt_index.get(key, GROUND_UNKNOWN)

            results.append({
                "file":         r.get("file", "?"),
                "subset_index": r.get("index"),
                "heuristic":    heuristic,
                "count1":       count1,
                "count2":       count2,
                "ground_truth": ground_truth,
            })

    # ------------------------------------------------------------------
    # Classify
    # ------------------------------------------------------------------
    TN             = [x for x in results if x["heuristic"] == "NOT_EQUIVALENT" and x["ground_truth"] == GROUND_NEQ]
    FN             = [x for x in results if x["heuristic"] == "NOT_EQUIVALENT" and x["ground_truth"] == GROUND_EQU]
    FN_unknown     = [x for x in results if x["heuristic"] == "NOT_EQUIVALENT" and x["ground_truth"] == GROUND_UNKNOWN]
    missed_neq     = [x for x in results if x["heuristic"] == "MAYBE_EQUIVALENT" and x["ground_truth"] == GROUND_NEQ]
    correct_pass   = [x for x in results if x["heuristic"] == "MAYBE_EQUIVALENT" and x["ground_truth"] == GROUND_EQU]
    unknown_pass   = [x for x in results if x["heuristic"] == "MAYBE_EQUIVALENT" and x["ground_truth"] == GROUND_UNKNOWN]

    total = len(results)
    not_eq_by_heuristic = [x for x in results if x["heuristic"] == "NOT_EQUIVALENT"]
    maybe_eq_by_heuristic = [x for x in results if x["heuristic"] == "MAYBE_EQUIVALENT"]

    # ------------------------------------------------------------------
    # Print detail table
    # ------------------------------------------------------------------
    print("=" * 78)
    print("FAST REJECTION TEST  --  50-pair LeetCode subset (EXISTS / IN / ANY)")
    print("=" * 78)
    print()
    print(f"  {'#':>2}  {'Heuristic':<18}  {'GT':<15}  {'C1':>3}  {'C2':>3}  {'Category':<20}  file")
    print("  " + "-" * 74)

    CATEGORY = {
        ("NOT_EQUIVALENT", GROUND_NEQ):     "True Negative  [TN]",
        ("NOT_EQUIVALENT", GROUND_EQU):     "FALSE NEGATIVE [FN]",
        ("NOT_EQUIVALENT", GROUND_UNKNOWN): "FN-Unknown     [?]",
        ("MAYBE_EQUIVALENT", GROUND_NEQ):   "Missed NEQ     [!]",
        ("MAYBE_EQUIVALENT", GROUND_EQU):   "Correct Pass   [OK]",
        ("MAYBE_EQUIVALENT", GROUND_UNKNOWN): "Unknown Pass   [?]",
    }

    for i, x in enumerate(results):
        cat = CATEGORY[(x["heuristic"], x["ground_truth"])]
        src = x["file"].split("/")[-1] if "/" in x["file"] else x["file"].split("\\")[-1]
        print(f"  {i:>2}  {x['heuristic']:<18}  {x['ground_truth']:<15}  "
              f"{x['count1']:>3}  {x['count2']:>3}  {cat:<20}  {src}")

    # ------------------------------------------------------------------
    # Summary report
    # ------------------------------------------------------------------
    print()
    print("=" * 78)
    print("SUMMARY REPORT")
    print("=" * 78)
    print()
    print(f"  Total pairs evaluated          : {total}")
    print(f"  Pairs flagged NOT_EQUIVALENT   : {len(not_eq_by_heuristic)}  ({100*len(not_eq_by_heuristic)/total:.0f}%)")
    print(f"  Pairs passed MAYBE_EQUIVALENT  : {len(maybe_eq_by_heuristic)}  ({100*len(maybe_eq_by_heuristic)/total:.0f}%)")
    print()
    print("  --- NOT_EQUIVALENT breakdown ---")
    print(f"  True Negatives  (TN)  -- correctly rejected  : {len(TN)}")
    print(f"  FALSE NEGATIVES (FN)  -- WRONG, GT says EQU  : {len(FN)}  <-- must be 0")
    print(f"  FN-Unknown            -- GT timed out        : {len(FN_unknown)}")
    print()
    print("  --- MAYBE_EQUIVALENT breakdown ---")
    print(f"  Missed NEQs           -- passed, GT says NEQ : {len(missed_neq)}  (heuristic missed)")
    print(f"  Correct Passes        -- passed, GT says EQU : {len(correct_pass)}")
    print(f"  Unknown Passes        -- passed, GT timed out: {len(unknown_pass)}")
    print()

    # Precision of rejection decisions (among pairs with known GT)
    known_rejections = TN + FN
    if known_rejections:
        precision = 100 * len(TN) / len(known_rejections)
        print(f"  Rejection precision   (TN / (TN+FN), known GT only)  : {precision:.1f}%")

    known_neq = TN + missed_neq
    if known_neq:
        recall = 100 * len(TN) / len(known_neq)
        print(f"  NEQ recall            (TN / (TN+missed), known GT)   : {recall:.1f}%")

    print()
    if len(FN) == 0:
        print("  SAFETY CHECK PASSED: zero False Negatives.")
        print("  The heuristic never incorrectly declared an equivalent pair NOT_EQUIVALENT.")
    else:
        print("  *** SAFETY CHECK FAILED: False Negatives detected! ***")
        print("  The following pairs were wrongly rejected:")
        for x in FN:
            print(f"    file={x['file']}  idx={x['subset_index']}")

    print()
    print("=" * 78)


if __name__ == "__main__":
    main()
