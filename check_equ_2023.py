import json
from collections import Counter

for label, path in [
    ("literature 2023", "experiments/2023_03_27/literature.out"),
    ("calcite 2023",    "experiments/2023_03_27/calcite.out"),
    ("leetcode 2023",   "experiments/2023_03_27/leetcode.out"),
]:
    c = Counter()
    equ_pairs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            states = r.get("states", [])
            if states:
                c[states[-1]] += 1
            if "NEQ" not in states and states and states[-1] == "EQU":
                equ_pairs.append(r)
    print(f"{label}: {dict(c)}  |  EQU = {len(equ_pairs)}")
    for r in equ_pairs[:3]:
        q1, q2 = r["pair"]
        print(f"  states={r['states']}  Q1: {q1[:70]}")
        print(f"  {'':>8}                   Q2: {q2[:70]}")
