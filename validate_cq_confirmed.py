"""
Validates fast_path_equivalence_check on the combined CQ-scoped confirmed-GT
subset produced by survey_cq_confirmed.py.

Input:  experiments/cq_confirmed_subset.jsonlines  (350 confirmed NEQ pairs)
Output: per-source breakdown + aggregate recall report
"""

import importlib.util
import json
import os

_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

SUBSET_FILE = os.path.join("experiments", "cq_confirmed_subset.jsonlines")

REJECT  = "NOT_EQUIVALENT"
PASS_ON = "MAYBE_EQUIVALENT"


def main():
    with open(SUBSET_FILE, encoding="utf-8") as fh:
        subset = [json.loads(l) for l in fh if l.strip()]

    rows = []
    parse_errors = []

    for i, rec in enumerate(subset):
        q1, q2 = rec["pair"]
        source  = rec.get("_source", "?")
        gt      = rec.get("_gt", "?")

        try:
            sa      = SemanticsAnalyzer(rec["schema"])
            verdict = sa.fast_path_equivalence_check(q1, q2, rec["constraint"])
            c1      = sa.count_bag_variables_filtered(q1, rec["constraint"])
            c2      = sa.count_bag_variables_filtered(q2, rec["constraint"])
        except Exception as e:
            parse_errors.append((i, source, str(e)[:80]))
            continue

        name = rec.get("name", rec.get("file", "?"))
        rows.append({
            "i":       i,
            "source":  source,
            "name":    name,
            "verdict": verdict,
            "gt":      gt,
            "c1":      c1,
            "c2":      c2,
        })

    W = 82
    print("=" * W)
    print("  FAST REJECTION VALIDATION -- Combined CQ-Confirmed Subset (350 NEQ pairs)")
    print("=" * W)
    print()

    sources = ["literature", "calcite", "leetcode"]

    for src in sources:
        src_rows = [r for r in rows if r["source"] == src]
        if not src_rows:
            continue

        tn   = [r for r in src_rows if r["verdict"] == REJECT]
        miss = [r for r in src_rows if r["verdict"] == PASS_ON]
        recall = 100 * len(tn) / len(src_rows) if src_rows else 0

        print(f"  [{src.upper()}]  {len(src_rows)} confirmed NEQ pairs")
        print(f"    True Negatives (caught early) : {len(tn)}")
        print(f"    Missed (passed to Z3)         : {len(miss)}")
        print(f"    NEQ Recall                    : {recall:.1f}%")

        if tn:
            print(f"    Caught pairs:")
            for r in tn:
                print(f"      [{r['i']:>3}] c1={r['c1']} c2={r['c2']}  {r['name']}")
        if miss and src != "leetcode":   # don't flood with 300+ missed leetcode pairs
            print(f"    Missed pairs:")
            for r in miss:
                print(f"      [{r['i']:>3}] c1={r['c1']} c2={r['c2']}  {r['name']}")
        elif miss and src == "leetcode":
            print(f"    (showing first 10 missed)")
            for r in miss[:10]:
                print(f"      [{r['i']:>3}] c1={r['c1']} c2={r['c2']}  {r['name']}")
            if len(miss) > 10:
                print(f"      ... and {len(miss) - 10} more")
        print()

    # -----------------------------------------------------------------------
    # Aggregate
    # -----------------------------------------------------------------------
    total   = len(rows)
    tn_all  = [r for r in rows if r["verdict"] == REJECT]
    miss_all = [r for r in rows if r["verdict"] == PASS_ON]

    print("=" * W)
    print("  AGGREGATE SUMMARY")
    print("=" * W)
    print()
    print(f"  Total confirmed NEQ pairs evaluated : {total}  (+ {len(parse_errors)} parse errors skipped)")
    print(f"  True Negatives [TN]                 : {len(tn_all)}")
    print(f"  Missed NEQ                          : {len(miss_all)}")
    if total:
        print(f"  Overall NEQ Recall                  : {100*len(tn_all)/total:.1f}%")
    print()
    print("  FALSE NEGATIVES: 0  (no confirmed EQU pairs in subset -- safety untested here,")
    print("  but guaranteed by Lemma 4.1 when both queries are CQ-scoped)")
    print()

    # -----------------------------------------------------------------------
    # Distribution of (c1, c2) counts for missed pairs -- understand the pattern
    # -----------------------------------------------------------------------
    from collections import Counter
    count_dist = Counter((r["c1"], r["c2"]) for r in miss_all)
    print("  Count distribution for missed NEQ pairs (c1, c2):")
    for (c1, c2), cnt in sorted(count_dist.items()):
        print(f"    c1={c1}  c2={c2}  -> {cnt} pairs")
    print()

    if parse_errors:
        print(f"  Parse errors ({len(parse_errors)} skipped):")
        for i, src, err in parse_errors[:10]:
            print(f"    [{i}] {src}: {err}")
        if len(parse_errors) > 10:
            print(f"    ... and {len(parse_errors) - 10} more")
        print()

    print("=" * W)


if __name__ == "__main__":
    main()
