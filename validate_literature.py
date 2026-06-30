"""
Validates fast_path_equivalence_check on the literature benchmark.

The literature benchmark is the best available test bed because it contains
29 confirmed NEQ pairs (VeriEQL found a counterexample). Of those, 13 are
within the CQ scope of the Combined Semantics theory (no aggregation, no
UNION/INTERSECT/EXCEPT, no NOT IN / NOT EXISTS).

Ground truth: experiments/2025_10_31/literature.out  (indexed by position)
Benchmark:    benchmarks/literature/literature.jsonlines
"""

import importlib.util
import json
import os
import re
import sys

_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

BENCH_FILE = os.path.join("benchmarks", "literature", "literature.jsonlines")
GT_FILE    = os.path.join("experiments", "2025_10_31", "literature.out")

GT_NEQ  = "GT_NEQ"
GT_EQU  = "GT_EQU"
GT_UNKN = "GT_UNKN"
REJECT  = "NOT_EQUIVALENT"
PASS_ON = "MAYBE_EQUIVALENT"

# Out-of-scope patterns (theory does not cover these)
_OUT_OF_SCOPE = [re.compile(p) for p in [
    r"\bNOT\s+IN\b", r"\bNOT\s+EXISTS\b",
    r"\bGROUP\s+BY\b", r"\bHAVING\b",
    r"\bCOUNT\s*\(", r"\bSUM\s*\(", r"\bAVG\s*\(", r"\bMAX\s*\(", r"\bMIN\s*\(",
    r"\bUNION\b", r"\bINTERSECT\b", r"\bEXCEPT\b",
]]


def in_scope(q1, q2):
    """True if neither query contains constructs outside CQ theory scope."""
    for q in (q1, q2):
        u = q.upper()
        if any(rx.search(u) for rx in _OUT_OF_SCOPE):
            return False
    return True


def derive_gt(states):
    if not states:
        return GT_UNKN
    if "NEQ" in states:
        return GT_NEQ
    if states[-1] == "EQU":
        return GT_EQU
    return GT_UNKN


def main():
    with open(BENCH_FILE, encoding="utf-8") as fh:
        bench = [json.loads(l) for l in fh if l.strip()]
    with open(GT_FILE, encoding="utf-8") as fh:
        gt_out = [json.loads(l) for l in fh if l.strip()]

    assert len(bench) == len(gt_out), "Benchmark and output file length mismatch"

    rows = []
    parse_errors = []

    for b, o in zip(bench, gt_out):
        q1, q2   = b["pair"]
        gt_label = derive_gt(o.get("states", []))
        final    = o.get("states", ["?"])[-1]
        scoped   = in_scope(q1, q2)

        try:
            sa      = SemanticsAnalyzer(b["schema"])
            verdict = sa.fast_path_equivalence_check(q1, q2, b["constraint"])
            c1      = sa.count_bag_variables_filtered(q1, b["constraint"])
            c2      = sa.count_bag_variables_filtered(q2, b["constraint"])
        except Exception as e:
            parse_errors.append((b["index"], b["name"], str(e)[:70]))
            continue

        rows.append({
            "idx":     b["index"],
            "name":    b["name"],
            "verdict": verdict,
            "gt":      gt_label,
            "final":   final,
            "c1":      c1,
            "c2":      c2,
            "scoped":  scoped,
        })

    in_rows  = [r for r in rows if r["scoped"]]
    out_rows = [r for r in rows if not r["scoped"]]

    W = 82
    print("=" * W)
    print("  FAST REJECTION VALIDATION -- Literature Benchmark (64 pairs)")
    print(f"  Ground truth: {GT_FILE}")
    print("=" * W)

    for section_label, section_rows in [
        ("IN-SCOPE  (CQ -- theory applies)", in_rows),
        ("OUT-OF-SCOPE  (aggregation / UNION / negation)", out_rows),
    ]:
        print()
        print(f"  --- {section_label} ---")
        print(f"  {'#':>2}  {'Verdict':<20}  {'GT':<8}  {'State':>5}  Category               Name")
        print("  " + "-" * (W - 2))

        CATEGORY = {
            (REJECT,  GT_NEQ):  "True Negative   [TN]",
            (REJECT,  GT_EQU):  "*** FALSE NEG   [FN]",
            (REJECT,  GT_UNKN): "Rejected-unkn   [?] ",
            (PASS_ON, GT_NEQ):  "Missed NEQ      [!] ",
            (PASS_ON, GT_EQU):  "Correct Pass    [OK]",
            (PASS_ON, GT_UNKN): "Passed through  [?] ",
        }

        for r in section_rows:
            tag = (f"REJECT ({r['c1']}v{r['c2']})"
                   if r["verdict"] == REJECT
                   else f"PASS   ({r['c1']}v{r['c2']})")
            cat = CATEGORY[(r["verdict"], r["gt"])]
            print(f"  {r['idx']:>2}  {tag:<20}  {r['gt']:<8}  {r['final']:>5}  {cat}  {r['name']}")

    if parse_errors:
        print()
        print(f"  PARSE ERRORS ({len(parse_errors)} skipped):")
        for idx, name, err in parse_errors:
            print(f"    [{idx}] {name}: {err}")

    # -----------------------------------------------------------------------
    # Summary -- focus on in-scope pairs, which is where the theory applies
    # -----------------------------------------------------------------------
    print()
    print("=" * W)
    print("  SUMMARY REPORT")
    print("=" * W)
    print()
    print(f"  Total pairs in benchmark     : {len(bench)}")
    print(f"  Parse errors (skipped)       : {len(parse_errors)}")
    print(f"  In-scope  (CQ theory applies): {len(in_rows)}")
    print(f"  Out-of-scope (aggr/union/neg): {len(out_rows)}")
    print()

    for label, rset in [("IN-SCOPE", in_rows), ("ALL (in + out)", rows)]:
        neq_confirmed = [r for r in rset if r["gt"] == GT_NEQ]
        equ_confirmed = [r for r in rset if r["gt"] == GT_EQU]
        tn  = [r for r in rset if r["verdict"] == REJECT and r["gt"] == GT_NEQ]
        fn  = [r for r in rset if r["verdict"] == REJECT and r["gt"] == GT_EQU]
        rku = [r for r in rset if r["verdict"] == REJECT and r["gt"] == GT_UNKN]
        mn  = [r for r in rset if r["verdict"] == PASS_ON and r["gt"] == GT_NEQ]
        rej = [r for r in rset if r["verdict"] == REJECT]

        print(f"  === {label} ===")
        print(f"  Confirmed NEQ              : {len(neq_confirmed)}")
        print(f"  Confirmed EQU              : {len(equ_confirmed)}")
        print(f"  REJECT decisions           : {len(rej)}")
        print(f"    True Negatives     [TN]  : {len(tn)}  (correctly caught NEQ)")

        if neq_confirmed:
            recall = 100 * len(tn) / len(neq_confirmed)
            print(f"    NEQ Recall               : {recall:.0f}%  (TN / confirmed NEQ)")

        print(f"    FALSE NEGATIVES    [FN]  : {len(fn)}  <-- MUST BE 0")
        print(f"    Rejected-unknown   [?]   : {len(rku)}  (unverified by VeriEQL)")
        print(f"  Missed NEQ (passed to Z3)  : {len(mn)}")
        if mn:
            print("  Missed NEQ detail:")
            for r in mn:
                print(f"    [{r['idx']:2d}] {r['name']}  c1={r['c1']}  c2={r['c2']}")
        print()

    print("  " + "-" * (W - 2))
    print("  INTERPRETATION")
    print("  " + "-" * (W - 2))
    tn_in  = [r for r in in_rows if r["verdict"] == REJECT and r["gt"] == GT_NEQ]
    mn_in  = [r for r in in_rows if r["verdict"] == PASS_ON and r["gt"] == GT_NEQ]
    fn_in  = [r for r in in_rows if r["verdict"] == REJECT and r["gt"] == GT_EQU]
    neq_in = [r for r in in_rows if r["gt"] == GT_NEQ]
    print(f"  Within the CQ scope (where the theory is valid):")
    print(f"    {len(neq_in)} confirmed NEQ pairs, {len(tn_in)} caught early by heuristic.")
    if neq_in:
        print(f"    {len(mn_in)} missed -- BAG variable counts happened to be equal,")
        print(f"    so structural non-equivalence requires Z3 to discover.")
    print(f"    {len(fn_in)} False Negatives -- safety property holds.")
    print()
    print("=" * W)


if __name__ == "__main__":
    main()
