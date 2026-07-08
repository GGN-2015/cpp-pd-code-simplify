# Python and C++ Comparison

The repository includes two implementations of the same mid-simplification
search:

- C++ executable: `pd_simplify`
- Python prototype: `mid_simplify_v5.py`

The differential test runner compares their JSON outputs exactly:

```sh
.\.venv\Scripts\python tools\compare_cpp_python.py --include-reference
```

On the local Windows development machine, this command matched all bundled
cases:

```text
[OK] unknot: found=False
[OK] trefoil: found=False
[OK] figure-eight: found=False
[OK] cinquefoil: found=False
[OK] reference-31: found=True
All 5 cases matched.
```

The benchmark runner measures wall-clock time and peak RSS:

```sh
.\.venv\Scripts\python tools\benchmark_cpp_python.py
```

One local run produced:

| Case | Engine | Time (s) | Peak RSS (MiB) | Return |
| --- | --- | ---: | ---: | ---: |
| trefoil | C++ | 0.020731 | 2.750 | 1 |
| trefoil | Python | 0.090680 | 21.727 | 1 |
| figure-eight | C++ | 0.018080 | 2.750 | 1 |
| figure-eight | Python | 0.103301 | 22.090 | 1 |
| reference-31 | C++ | 7.019658 | 5.789 | 0 |
| reference-31 | Python | 32.406291 | 22.879 | 0 |

Return code `0` means a simplification witness was found. Return code `1`
means the run completed normally but found no witness.
