"""
Extracts up to 50 query pairs from the LeetCode benchmark where at least one
query contains EXISTS, NOT EXISTS, IN (, or ANY.
Output: experiments/leetcode_exist_any_in_semantics_subset.jsonlines
"""

import json
import os

BENCHMARK_FILE = os.path.join("benchmarks", "leetcode", "leetcode.jsonlines")
OUTPUT_FILE = os.path.join("experiments", "leetcode_exist_any_in_semantics_subset.jsonlines")
TARGET_COUNT = 50
KEYWORDS = ["EXISTS", "NOT EXISTS", " IN (", "ANY"]


def matches(query: str) -> bool:
    upper = query.upper()
    return any(kw in upper for kw in KEYWORDS)


def main():
    collected = []

    with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [warn] Line {line_num}: JSON parse error — {e}")
                continue

            pair = record.get("pair", [])
            if len(pair) < 2:
                continue

            q1, q2 = pair[0], pair[1]
            if matches(q1) or matches(q2):
                collected.append(record)
                if len(collected) >= TARGET_COUNT:
                    break

    os.makedirs("experiments", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for record in collected:
            out.write(json.dumps(record) + "\n")

    print(f"Collected {len(collected)} pairs -> {OUTPUT_FILE}")

    # Summary: which keywords triggered each pair
    for i, record in enumerate(collected):
        q1, q2 = record["pair"]
        hits = [kw for kw in KEYWORDS if kw in q1.upper() or kw in q2.upper()]
        print(f"  [{i:2d}] idx={record.get('index', '?')}  file={record.get('file', '?')}  keywords={hits}")


if __name__ == "__main__":
    main()
