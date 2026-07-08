# Python and C++ Comparison

The repository includes two direct implementations of the same
mid-simplification search:

- C++ executable: `pd_simplify`
- Python prototype: `mid_simplify_v5.py`

It also includes a PyPI-ready Python C++ interface package documented in
[Python C++ Interface](python-interface.md).

## Differential Testing

The differential test runner compares their JSON outputs exactly. Both
implementations use the default preprocessing pipeline first: R1-move removal,
then nugatory-crossing removal.

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
current local results include the Python C++ interface and are documented in
[Benchmarking](benchmarking.md).
