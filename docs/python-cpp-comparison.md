# Python and C++ Comparison

The repository includes two implementations of the same mid-simplification
search:

- C++ executable: `pd_simplify`
- Python prototype: `mid_simplify_v5.py`

## Differential Testing

The differential test runner compares their JSON outputs exactly:

```sh
.\.venv\Scripts\python tools\compare_cpp_python.py --include-reference
```

To compare every deterministic benchmark input as well:

```sh
.\.venv\Scripts\python tools\compare_cpp_python.py --include-benchmark
```

On Linux and macOS, use `.venv/bin/python` instead of
`.\.venv\Scripts\python`.

Return code `0` from either simplifier means a simplification witness was
found. Return code `1` means the run completed normally but found no witness.

## Benchmarking

Use the benchmark runner to measure wall-clock time and peak RSS:

```sh
.\.venv\Scripts\python tools\benchmark_cpp_python.py --repeat 3
```

The benchmark dataset, chart-generation command, committed PNG chart, and
current local results are documented in [Benchmarking](benchmarking.md).
