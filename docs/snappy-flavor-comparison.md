# SnapPy/Spherogram-Flavor Comparison

This page records a small regression test driven by
[`snappy_flavor_test.py`](../snappy_flavor_test.py). The test compares this
project's C++ CLI against fixtures derived from Spherogram doctests and
Spherogram link unit tests.

## Purpose

The goal is not to prove that the two programs implement the same
simplification algorithm. They do not. The goal is to check that this project
reaches the same final crossing counts on a small set of SnapPy/Spherogram
flavored examples:

- examples where Spherogram reduces a diagram to a smaller crossing count;
- examples where Spherogram's basic simplifier keeps a prime-knot seed at its
  original crossing count;
- a deterministic K14n2345-derived fixture that Spherogram globally simplifies
  from 33 crossings to 14 crossings.

The comparison is useful because the fixture sources come from an independent
software ecosystem. It catches regressions where the C++ reducer either fails
to reach a known target crossing count or accidentally changes a one-component
fixture into a result with the wrong component count.

## Method

For each fixture, the script runs:

1. `pd_simplify` on the fixture PD code with this project's normal reduction
   route.
2. `spherogram.Link(...).simplify(MODE)` in-process, where `MODE` is either
   `basic` or `global`, matching the fixture source.
3. A status check requiring:
   - C++ final crossing count equals the expected Spherogram target;
   - Spherogram final crossing count equals the same target;
   - final PD-code crossing counts match that target;
   - both final diagrams report one component;
   - C++ did not time out or hit the brute-force resource guard.

The test does not require the final PD-code strings to be identical. Different
PD strings can encode equivalent diagrams, and the two programs use different
renumbering conventions. The script records both final PD strings in the CSV
for inspection, but the pass/fail criterion is crossing count and component
count.

Timing should be read carefully. The C++ timing is CLI wall time and includes
process startup, argument parsing, JSON formatting, and JSON parsing by the
test script. The Spherogram timing is in-process wall time and excludes Python
import startup. The timing numbers therefore compare workflow cost in this
script, not isolated kernel speed.

The recorded run used:

```sh
python snappy_flavor_test.py \
  --cpp-exe build/bin/pd_simplify.exe \
  --csv docs/assets/snappy_flavor_comparison.csv \
  --max-paths -1 \
  --reduction-round -1 \
  --max-thread 16 \
  --bruteforce-budget 200000 \
  --timeout 300 \
  --quit-at-expected \
  --keep-going
```

On Windows, the local WinLibs runtime directory was prepended to `PATH` before
running the command so the C++ executable could load its runtime DLLs.

## Results

Generated at local time `2026-07-11 11:41:24 +08:00`.

| Case | Source Mode | Input | Expected | C++ Final | Spherogram Final | C++ Time (s) | Spherogram Time (s) | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `spherogram_simplify_basic_7_to_4` | `basic` | 7 | 4 | 4 | 4 | 0.010600500 | 0.000510100 | ok |
| `spherogram_untwist_square_knot_9_to_6` | `global` | 9 | 6 | 6 | 6 | 0.010425300 | 0.004486400 | ok |
| `spherogram_k14n2345_backtrack30_seed2_33_to_14` | `global` | 33 | 14 | 14 | 14 | 0.022044800 | 0.006147300 | ok |
| `spherogram_unit_3_1_stays_3` | `basic` | 3 | 3 | 3 | 3 | 0.013174300 | 0.000204500 | ok |
| `spherogram_unit_7_2_stays_7` | `basic` | 7 | 7 | 7 | 7 | 22.714193300 | 0.000377000 | ok |
| `spherogram_unit_8_3_stays_8` | `basic` | 8 | 8 | 8 | 8 | 20.597121400 | 0.000416500 | ok |
| `spherogram_unit_8_13_stays_8` | `basic` | 8 | 8 | 8 | 8 | 27.828623200 | 0.000422200 | ok |

Summary:

- Cases run: `7`
- Passed: `7`
- Failed: `0`
- C++ total wall time: `71.196182800 s`
- Spherogram total in-process time: `0.012564000 s`
- C++ median wall time: `0.022044800 s`
- Spherogram median in-process time: `0.000422200 s`

The first three reducing cases complete quickly in the C++ CLI, including the
33-to-14 K14n2345-derived fixture. The three stable prime-knot seeds are much
slower on the C++ side because the current reducer tries to establish that no
configured simplification route is available, including brute-force
green-path checks under the configured budget. Spherogram's `basic` mode uses a
different local simplification strategy and returns almost immediately on
these already-stable seeds.

Raw result rows are stored in
[`docs/assets/snappy_flavor_comparison.csv`](assets/snappy_flavor_comparison.csv).

