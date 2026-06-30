"""
Extracts up to 50 query pairs from the LeetCode benchmark that fall within
the scope of the Combined Semantics theory (Sara Cohen, PODS 2006).

Inclusion criteria  (at least one query in the pair must satisfy):
  - Contains a POSITIVE existence/membership predicate: EXISTS or IN (subquery)

Exclusion criteria  (either query triggers disqualification):
  - NOT IN / NOT EXISTS           (negation -- outside CQ scope)
  - GROUP BY / HAVING             (aggregation)
  - COUNT / SUM / AVG / MAX / MIN (aggregation functions)
  - UNION / INTERSECT / EXCEPT    (set operations)
  - UPDATE / DELETE / INSERT      (not SELECT queries)

Diversity: at most MAX_PER_FILE pairs from each source file.

Output: experiments/leetcode_cq_positive_subset.jsonlines
"""

import json
import os
import re
from collections import defaultdict

BENCHMARK_FILE = os.path.join("benchmarks", "leetcode", "leetcode.jsonlines")
OUTPUT_FILE    = os.path.join("experiments", "leetcode_cq_positive_subset.jsonlines")
# Note: the entire LeetCode benchmark contains only ~51 pairs that satisfy the
# CQ positive-EXISTS/IN scope (no NOT IN, NOT EXISTS, aggregation, or set ops).
# MAX_PER_FILE is set to 999 because enforcing a per-file cap would further
# reduce an already tiny pool.
TARGET_COUNT   = 100   # take everything that qualifies (pool is ~51 total)
MAX_PER_FILE   = 999   # no cap -- pool is too small to enforce diversity

# Positive signal: at least one query must contain one of these
_WANT = [
    r"\bEXISTS\b",
    r"\bIN\b\s*\(",        # IN followed by ( -- i.e. IN (subquery or value list)
]

# Disqualifiers: either query having any of these removes the pair
_EXCLUDE = [
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
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bINSERT\b",
]

_WANT_RE    = [re.compile(p) for p in _WANT]
_EXCLUDE_RE = [re.compile(p) for p in _EXCLUDE]


def has_positive_signal(q: str) -> bool:
    u = q.upper()
    return any(rx.search(u) for rx in _WANT_RE)


def is_disqualified(q: str) -> bool:
    u = q.upper()
    return any(rx.search(u) for rx in _EXCLUDE_RE)


def main():
    collected  = []
    per_file   = defaultdict(int)
    seen_pairs = set()          # deduplicate within the output

    with open(BENCHMARK_FILE, encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            pair = rec.get("pair", [])
            if len(pair) < 2:
                continue

            q1, q2 = pair

            # per-file diversity cap
            src = rec.get("file", "")
            if per_file[src] >= MAX_PER_FILE:
                continue

            # disqualification check
            if is_disqualified(q1) or is_disqualified(q2):
                continue

            # positive-signal check
            if not (has_positive_signal(q1) or has_positive_signal(q2)):
                continue

            # deduplication (same Q1+Q2 can appear across files)
            key = (q1.strip(), q2.strip())
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            per_file[src] += 1
            collected.append(rec)

            if len(collected) >= TARGET_COUNT:
                break

    os.makedirs("experiments", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        for rec in collected:
            fh.write(json.dumps(rec) + "\n")

    # Report
    print(f"Collected {len(collected)} pairs -> {OUTPUT_FILE}")
    print()

    src_counts = defaultdict(int)
    for rec in collected:
        src_counts[rec.get("file", "?").split("/")[-1]] += 1

    print("Source file distribution:")
    for src, cnt in sorted(src_counts.items(), key=lambda x: -x[1]):
        print(f"  {src:<20s} {cnt} pairs")

    print()
    print("Sample pairs:")
    for i, rec in enumerate(collected[:5]):
        q1, q2 = rec["pair"]
        print(f"  [{i}] {rec['file'].split('/')[-1]}")
        print(f"       Q1: {q1[:90]}")
        print(f"       Q2: {q2[:90]}")


if __name__ == "__main__":
    main()
