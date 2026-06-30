"""
Scans literature, calcite, and leetcode benchmarks for query pairs that are:
  1. Within CQ scope (no NOT IN, NOT EXISTS, GROUP BY, HAVING, aggregation,
     UNION, INTERSECT, EXCEPT)
  2. Have confirmed ground truth from VeriEQL (states contains NEQ, or last
     state is EQU — not just TMO / NSE / NIE / OOM / SYN)

Uses the 2025_10_31 experiment runs for all three benchmarks.
Outputs a combined subset to experiments/cq_confirmed_subset.jsonlines.
"""

import json
import os
import re
from collections import defaultdict

# ---------------------------------------------------------------------------
# Scope filter (same patterns as SemanticsAnalyzer._is_cq_scoped)
# ---------------------------------------------------------------------------
_OUT_RE = [re.compile(p) for p in [
    r"\bNOT\s+IN\b",
    r"\bNOT\s+EXISTS\b",
    r"\bGROUP\s+BY\b",
    r"\bHAVING\b",
    r"\bCOUNT\s*\(",
    r"\bSUM\s*\(",
    r"\bAVG\s*\(",
    r"\bMAX\s*\(",
    r"\bMIN\s*\(",
    r"\bUNION\b",
    r"\bINTERSECT\b",
    r"\bEXCEPT\b",
]]

def is_cq_scoped(q1: str, q2: str) -> bool:
    for q in (q1, q2):
        u = q.upper()
        if any(rx.search(u) for rx in _OUT_RE):
            return False
    return True


# ---------------------------------------------------------------------------
# Ground truth derivation
# ---------------------------------------------------------------------------
GT_NEQ  = "GT_NEQ"
GT_EQU  = "GT_EQU"
GT_UNKN = "GT_UNKN"

def derive_gt(states: list) -> str:
    if not states:
        return GT_UNKN
    if "NEQ" in states:
        return GT_NEQ
    if states[-1] == "EQU":
        return GT_EQU
    return GT_UNKN


# ---------------------------------------------------------------------------
# Load a .out file, return list of records (positional)
# ---------------------------------------------------------------------------
def load_out(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def load_bench(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


# ---------------------------------------------------------------------------
# Datasets: (label, bench_path, out_path, match_strategy)
# match_strategy: "positional" or "by_pair"
# ---------------------------------------------------------------------------
DATASETS = [
    (
        "literature",
        os.path.join("benchmarks", "literature", "literature.jsonlines"),
        os.path.join("experiments", "2025_10_31", "literature.out"),
        "positional",
    ),
    (
        "calcite",
        os.path.join("benchmarks", "calcite", "calcite2.jsonlines"),
        os.path.join("experiments", "2025_10_31", "calcite.out"),
        "positional",
    ),
    (
        "leetcode",
        os.path.join("benchmarks", "leetcode", "leetcode.jsonlines"),
        os.path.join("experiments", "2025_10_31", "leetcode.out"),
        "by_pair",
    ),
]

OUTPUT_FILE = os.path.join("experiments", "cq_confirmed_subset.jsonlines")


def main():
    combined: list[dict] = []
    summary_rows: list[tuple] = []   # (dataset, total, cq_scoped, confirmed_neq, confirmed_equ)

    for label, bench_path, out_path, strategy in DATASETS:
        bench = load_bench(bench_path)
        out   = load_out(out_path)

        # Build a lookup for "by_pair" strategy
        pair_to_out: dict[tuple, dict] = {}
        if strategy == "by_pair":
            for o in out:
                key = (o["pair"][0], o["pair"][1])
                pair_to_out[key] = o

        total = len(bench)
        cq_scoped_count = 0
        confirmed_neq: list[dict] = []
        confirmed_equ: list[dict] = []

        for i, b in enumerate(bench):
            q1, q2 = b["pair"]
            if not is_cq_scoped(q1, q2):
                continue
            cq_scoped_count += 1

            # Retrieve output record
            if strategy == "positional":
                if i >= len(out):
                    continue
                o = out[i]
            else:
                o = pair_to_out.get((q1, q2))
                if o is None:
                    continue

            gt = derive_gt(o.get("states", []))

            # Build enriched record for the subset
            rec = dict(b)
            rec["_source"]    = label
            rec["_gt"]        = gt
            rec["_gt_states"] = o.get("states", [])

            if gt == GT_NEQ:
                confirmed_neq.append(rec)
            elif gt == GT_EQU:
                confirmed_equ.append(rec)

        summary_rows.append((label, total, cq_scoped_count,
                             len(confirmed_neq), len(confirmed_equ)))
        combined.extend(confirmed_neq)
        combined.extend(confirmed_equ)

    # Write combined subset
    os.makedirs("experiments", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        for rec in combined:
            fh.write(json.dumps(rec) + "\n")

    # ---------------------------------------------------------------------------
    # Report
    # ---------------------------------------------------------------------------
    W = 80
    print("=" * W)
    print("  CQ-SCOPE + CONFIRMED-GT SURVEY  (all three benchmarks)")
    print("=" * W)
    print()
    print(f"  {'Dataset':<14}  {'Total':>7}  {'CQ-scoped':>10}  {'Conf-NEQ':>9}  {'Conf-EQU':>9}")
    print("  " + "-" * (W - 2))
    for label, total, cq, cn, ce in summary_rows:
        pct = 100 * cq / total if total else 0
        print(f"  {label:<14}  {total:>7}  {cq:>8} ({pct:4.1f}%)  {cn:>9}  {ce:>9}")

    total_cq  = sum(r[2] for r in summary_rows)
    total_cn  = sum(r[3] for r in summary_rows)
    total_ce  = sum(r[4] for r in summary_rows)
    print("  " + "-" * (W - 2))
    print(f"  {'TOTAL':<14}  {sum(r[1] for r in summary_rows):>7}  {total_cq:>10}  {total_cn:>9}  {total_ce:>9}")
    print()
    print(f"  Combined confirmed subset: {len(combined)} pairs")
    print(f"    {total_cn} NEQ  +  {total_ce} EQU")
    print(f"  Written to: {OUTPUT_FILE}")
    print()

    # Per-dataset breakdown of confirmed pairs
    for label, _, _, cn, ce in summary_rows:
        if cn + ce == 0:
            continue
        print(f"  --- {label} confirmed pairs ---")
        neq_recs = [r for r in combined if r["_source"] == label and r["_gt"] == GT_NEQ]
        equ_recs = [r for r in combined if r["_source"] == label and r["_gt"] == GT_EQU]
        if neq_recs:
            print(f"  NEQ ({len(neq_recs)}):")
            for r in neq_recs:
                name = r.get("name", r.get("file", "?"))
                q1, q2 = r["pair"]
                print(f"    [{r.get('index','?'):>3}] {name}")
                print(f"          Q1: {q1[:85]}")
                print(f"          Q2: {q2[:85]}")
        if equ_recs:
            print(f"  EQU ({len(equ_recs)}):")
            for r in equ_recs[:10]:   # cap at 10 for readability
                name = r.get("name", r.get("file", "?"))
                q1, q2 = r["pair"]
                print(f"    [{r.get('index','?'):>3}] {name}")
                print(f"          Q1: {q1[:85]}")
                print(f"          Q2: {q2[:85]}")
            if len(equ_recs) > 10:
                print(f"    ... and {len(equ_recs) - 10} more EQU pairs")
        print()

    print("=" * W)


if __name__ == "__main__":
    main()
