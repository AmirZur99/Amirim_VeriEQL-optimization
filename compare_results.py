#!/usr/bin/env python3
"""
Compare VeriEQL benchmark outputs.

Usage:
    python compare_results.py <reference.out> <new.out>

Example:
    python compare_results.py experiments/2025_10_31/literature.out \
                              experiments/amir_cm_test/literature.out
"""
import sys
from pathlib import Path

import ujson


def load_results(path):
    results = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = ujson.loads(line)
            results[r["index"]] = r
    return results


def final_verdict(states):
    """
    Derive the definitive answer from a states list.
    - Last state is NEQ → NEQ  (counterexample found, always terminates)
    - Last state is EQU → EQU  (stopped by CM bound or all bounds exhausted)
    - Last state is TMO/OOM → TIMEOUT  (did not reach a conclusion)
    - Anything else → that state (SYN, NSE, etc.)
    """
    if not states:
        return "TIMEOUT"
    last = states[-1]
    if last in ("TMO", "OOM", None):
        return "TIMEOUT"
    return last


def main(reference_path, new_path):
    ref = load_results(reference_path)
    new = load_results(new_path)

    regressions, improvements, same, missing = [], [], [], []

    for idx in sorted(ref):
        if idx not in new:
            missing.append(idx)
            continue

        r_states = ref[idx]["states"]
        n_states  = new[idx]["states"]
        r_verdict = final_verdict(r_states)
        n_verdict = final_verdict(n_states)
        r_iters   = len(r_states)
        n_iters   = len(n_states)

        entry = dict(
            index=idx,
            file=ref[idx].get("file", ""),
            r_verdict=r_verdict,
            n_verdict=n_verdict,
            r_iters=r_iters,
            n_iters=n_iters,
        )

        if r_verdict in ("EQU", "NEQ") and n_verdict != r_verdict:
            regressions.append(entry)
        elif r_verdict == "TIMEOUT" and n_verdict in ("EQU", "NEQ"):
            improvements.append(entry)          # TMO → definitive answer
        elif r_verdict == n_verdict and n_iters < r_iters:
            improvements.append(entry)          # same answer, fewer iterations
        else:
            same.append(entry)

    SEP = "=" * 72
    print(f"\n{SEP}")
    print(f"  reference : {reference_path}")
    print(f"  new       : {new_path}")
    print(SEP)

    if regressions:
        print(f"\n[REGRESSIONS] {len(regressions)}  ← investigate these")
        for e in regressions:
            print(f"  idx={e['index']:3d}  ({e['file']:<30s})  "
                  f"{e['r_verdict']} → {e['n_verdict']}  "
                  f"(iters {e['r_iters']} → {e['n_iters']})")
    else:
        print("\n[REGRESSIONS] none — all previously decided queries still correct ✓")

    print(f"\n[IMPROVEMENTS] {len(improvements)}")
    for e in improvements:
        if e["r_verdict"] != e["n_verdict"]:
            change = f"{e['r_verdict']} → {e['n_verdict']}"
        else:
            change = f"{e['n_verdict']} (same)"
        print(f"  idx={e['index']:3d}  ({e['file']:<30s})  "
              f"{change}  iters: {e['r_iters']} → {e['n_iters']}")

    print(f"\n[SAME / UNCHANGED] {len(same)}")

    if missing:
        print(f"\n[MISSING from new output] indices: {missing}")

    # ---- verdict-level summary table ----
    states_map = {}
    for idx in sorted(ref):
        if idx not in new:
            continue
        r = final_verdict(ref[idx]["states"])
        n = final_verdict(new[idx]["states"])
        states_map.setdefault((r, n), []).append(idx)

    header = 'ref \\ new'
    print(f"\n{SEP}")
    print("  Verdict transition matrix  (ref → new)")
    print(f"  {header:<12}  EQU   NEQ   TIMEOUT  OTHER")
    for r_v in ("EQU", "NEQ", "TIMEOUT"):
        row = []
        for n_v in ("EQU", "NEQ", "TIMEOUT", "OTHER"):
            if n_v == "OTHER":
                cnt = sum(len(v) for (rv, nv), v in states_map.items()
                          if rv == r_v and nv not in ("EQU", "NEQ", "TIMEOUT"))
            else:
                cnt = len(states_map.get((r_v, n_v), []))
            row.append(f"{cnt:5d}")
        print(f"  {r_v:<12}  {'  '.join(row)}")

    print(f"\n  Total queries : {len(ref)}")
    print(f"  Regressions   : {len(regressions)}")
    print(f"  Improvements  : {len(improvements)}")
    print(f"  Unchanged     : {len(same)}")
    print(f"{SEP}\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
