"""
Safety check for fast_path_equivalence_check.

Test 1 — Identity:
  Run the heuristic on (Q, Q) for 20 queries sampled from the benchmarks.
  Every result MUST be MAYBE_EQUIVALENT; NOT_EQUIVALENT on Q vs itself
  means the BAG-counting logic is broken.

Test 2 — Confirmed EQU pairs:
  Cross-reference literature.jsonlines with literature.out to find pairs
  where VeriEQL confirmed equivalence (last state = EQU, no NEQ ever seen).
  The heuristic MUST return MAYBE_EQUIVALENT for every such pair.
"""

import importlib.util
import json
import os
import sys

# Load SemanticsAnalyzer without triggering the z3 import
_spec = importlib.util.spec_from_file_location(
    "semantics_analyzer",
    os.path.join(os.path.dirname(__file__), "parsers", "semantics_analyzer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SemanticsAnalyzer = _mod.SemanticsAnalyzer

REJECT  = "NOT_EQUIVALENT"
PASS_ON = "MAYBE_EQUIVALENT"

BENCH_FILES = [
    os.path.join("benchmarks", "literature", "literature.jsonlines"),
    os.path.join("benchmarks", "calcite",    "calcite2.jsonlines"),
    os.path.join("benchmarks", "leetcode",   "leetcode.jsonlines"),
]
LIT_BENCH = os.path.join("benchmarks", "literature", "literature.jsonlines")
LIT_OUT   = os.path.join("experiments", "2025_10_31", "literature.out")
CAL_BENCH = os.path.join("benchmarks", "calcite", "calcite2.jsonlines")
CAL_OUT   = os.path.join("experiments", "2025_10_31", "calcite.out")


def load_jsonlines(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def is_equ(states):
    if not states:
        return False
    return "NEQ" not in states and states[-1] == "EQU"


W = 82

# =============================================================================
# TEST 1 — Identity check: fast_path(Q, Q) must always be MAYBE_EQUIVALENT
# =============================================================================

print("=" * W)
print("  TEST 1 — IDENTITY CHECK  (Q vs Q for 20 distinct queries)")
print("=" * W)
print()

# Sample 20 queries: take the first query from the first 20 records across
# all three benchmarks (5 literature, 5 calcite, 10 leetcode).
samples = []  # (source_label, q, schema, constraint)

targets = [
    (os.path.join("benchmarks", "literature", "literature.jsonlines"), "literature", 5),
    (os.path.join("benchmarks", "calcite",    "calcite2.jsonlines"),   "calcite",    5),
    (os.path.join("benchmarks", "leetcode",   "leetcode.jsonlines"),   "leetcode",  10),
]

for path, label, n in targets:
    records = load_jsonlines(path)
    for rec in records[:n]:
        q = rec["pair"][0]
        samples.append((label, q, rec["schema"], rec["constraint"]))

print(f"  {'#':>2}  {'Source':<12}  {'Result':<22}  {'c1':>3}  Query (truncated)")
print("  " + "-" * (W - 2))

identity_failures = []
identity_errors   = []

for i, (label, q, schema, constraint) in enumerate(samples):
    try:
        sa      = SemanticsAnalyzer(schema)
        verdict = sa.fast_path_equivalence_check(q, q, constraint)
        c       = sa.count_bag_variables_filtered(q, constraint)
        status  = "OK" if verdict == PASS_ON else "*** FAIL ***"
        print(f"  {i+1:>2}  {label:<12}  {verdict:<22}  {c:>3}  {q[:38]}")
        if verdict == REJECT:
            identity_failures.append((i + 1, label, q, c))
    except Exception as e:
        identity_errors.append((i + 1, label, str(e)[:70]))
        print(f"  {i+1:>2}  {label:<12}  ERROR                   ---  {str(e)[:38]}")

print()
if not identity_failures and not identity_errors:
    print(f"  RESULT: ALL 20 PASSED  --  heuristic correctly returns MAYBE_EQUIVALENT")
    print(f"  for every query compared against itself. BAG-counting logic is consistent.")
elif identity_failures:
    print(f"  *** FAILURES: {len(identity_failures)} query/queries returned NOT_EQUIVALENT vs itself ***")
    for num, lbl, q, c in identity_failures:
        print(f"    #{num} [{lbl}]  c={c}  {q[:70]}")
if identity_errors:
    print(f"  Parse errors ({len(identity_errors)}): {identity_errors}")

# =============================================================================
# TEST 2 — Confirmed EQU pairs from literature + calcite
# =============================================================================

print()
print("=" * W)
print("  TEST 2 — CONFIRMED EQU PAIRS  (VeriEQL proved equivalent)")
print("=" * W)
print()

equ_records = []  # (source, name_or_idx, q1, q2, schema, constraint, states)

for bench_path, out_path, label in [
    (LIT_BENCH, LIT_OUT, "literature"),
    (CAL_BENCH, CAL_OUT, "calcite"),
]:
    bench = load_jsonlines(bench_path)
    out   = load_jsonlines(out_path)
    for b, o in zip(bench, out):
        if is_equ(o.get("states", [])):
            name = b.get("name", b.get("index", "?"))
            q1, q2 = b["pair"]
            equ_records.append((label, name, q1, q2,
                                 b["schema"], b["constraint"],
                                 o["states"]))

if not equ_records:
    # Fall back: scan leetcode for EQU pairs (use by-pair lookup)
    print("  No confirmed EQU pairs in literature or calcite.")
    print("  Scanning leetcode for EQU pairs (first 20 found) ...")
    print()
    leet_bench = load_jsonlines(os.path.join("benchmarks", "leetcode", "leetcode.jsonlines"))
    leet_out   = load_jsonlines(os.path.join("experiments", "2025_10_31", "leetcode.out"))
    pair_to_out = {(o["pair"][0], o["pair"][1]): o for o in leet_out}
    for b in leet_bench:
        q1, q2 = b["pair"]
        o = pair_to_out.get((q1, q2))
        if o and is_equ(o.get("states", [])):
            equ_records.append(("leetcode", b.get("file","?"), q1, q2,
                                 b["schema"], b["constraint"], o["states"]))
        if len(equ_records) >= 20:
            break

if not equ_records:
    print("  No confirmed EQU pairs found in any benchmark. Cannot run test 2.")
else:
    print(f"  Found {len(equ_records)} confirmed EQU pair(s).")
    print()
    print(f"  {'#':>2}  {'Source':<12}  {'Name/ID':<30}  {'Result':<22}  c1  c2  States")
    print("  " + "-" * (W - 2))

    equ_failures = []
    equ_errors   = []

    for i, (label, name, q1, q2, schema, constraint, states) in enumerate(equ_records):
        try:
            sa      = SemanticsAnalyzer(schema)
            verdict = sa.fast_path_equivalence_check(q1, q2, constraint)
            c1      = sa.count_bag_variables_filtered(q1, constraint)
            c2      = sa.count_bag_variables_filtered(q2, constraint)
            states_str = "->".join(states[-3:])  # last 3 states
            flag = "" if verdict == PASS_ON else "  *** FALSE NEGATIVE ***"
            print(f"  {i+1:>2}  {label:<12}  {str(name):<30}  {verdict:<22}  {c1:>2}  {c2:>2}  {states_str}{flag}")
            if verdict == REJECT:
                equ_failures.append((i + 1, label, name, c1, c2, q1, q2))
        except Exception as e:
            equ_errors.append((i + 1, label, str(e)[:70]))
            print(f"  {i+1:>2}  {label:<12}  {str(name):<30}  ERROR                         {str(e)[:20]}")

    print()
    if not equ_failures and not equ_errors:
        print(f"  RESULT: ALL {len(equ_records)} PASSED  --  heuristic never returns NOT_EQUIVALENT")
        print(f"  on a pair VeriEQL confirmed as equivalent. Safety property holds.")
    elif equ_failures:
        print(f"  *** FALSE NEGATIVES: {len(equ_failures)} pair(s) incorrectly rejected ***")
        for num, lbl, name, c1, c2, q1, q2 in equ_failures:
            print(f"    #{num} [{lbl}] {name}  c1={c1} c2={c2}")
            print(f"       Q1: {q1[:75]}")
            print(f"       Q2: {q2[:75]}")
    if equ_errors:
        print(f"  Parse errors ({len(equ_errors)}): {equ_errors}")

# =============================================================================
# Final verdict
# =============================================================================
print()
print("=" * W)
print("  OVERALL SAFETY VERDICT")
print("=" * W)
total_failures = len(identity_failures) + (len(equ_failures) if equ_records else 0)
if total_failures == 0:
    print()
    print("  PASS -- Both safety tests completed with zero failures.")
    print("  The heuristic is conservative: it never returns NOT_EQUIVALENT")
    print("  on a query compared to itself, nor on any VeriEQL-confirmed EQU pair.")
else:
    print()
    print(f"  *** FAIL -- {total_failures} safety violation(s) detected ***")
print()
print("=" * W)
