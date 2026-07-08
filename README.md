# cpp-pd-code-simplify

A small, dependency-free C++14 project for finding mid-simplification
witnesses in knot and link planar diagram codes.

The implementation follows the algorithmic structure of the local research
prototype:

- build oriented crossing entries from a PD code;
- build the dual graph of diagram faces;
- track link components explicitly, including crossingless components that
  cannot be represented directly by a plain PD code;
- enumerate candidate red boundary paths;
- search shorter green paths in the dual graph;
- validate over/under consistency for the candidate disk.

The repository also includes a refactored Python prototype in
[`mid_simplify_v5.py`](mid_simplify_v5.py). It exposes the same core
algorithm as an importable API and a CLI for differential testing.

For a more detailed description of the algorithm and its correctness
argument, see [Algorithm and Correctness](docs/algorithm-and-correctness.md).

## Build

The project uses CMake and only the C++ standard library.

### Windows

```powershell
.\scripts\build.ps1
```

### Linux and macOS

```sh
./scripts/build.sh
```

Manual CMake commands work on every platform:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
ctest --test-dir build --build-config Release --output-on-failure
```

## Command Line

```sh
pd_simplify --pd-code "PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]"
```

The CLI follows the same input style as `cppkh`: pass a literal `PD[...]`
string, a file, or every `.txt` and `.pd` file in a directory.

```sh
pd_simplify --pd-file diagram.pd --json
pd_simplify --pd-dir samples
```

`--pd-code` may contain one or more `PD[...]` blocks. Input files may contain
multiple PD codes, one or more standard `PD[...]` blocks, or labelled lines
such as `trefoil: PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]`. If no input is
given, the executable tries to read `PD.txt` from the current directory.
Python-style crossing lists are still accepted for compatibility. In the CLI,
standard `PD[]` input is treated as one crossingless unknot component.

Plain PD codes cannot store components with no crossings. If a previous
operation has already produced such components, pass their count explicitly:

```sh
pd_simplify --known-crossingless-components 1 --input diagram.pd
```

When testing a move that removes crossings, the CLI can report how many link
components would become crossingless:

```sh
pd_simplify --remove-crossings 0,1,2 "[(1,5,2,4),(3,1,4,6),(5,3,6,2)]"
```

The process exits with code `0` when a witness is found, `1` when no witness
is found, and `2` for invalid input or runtime errors.

## Python Prototype

Create a local virtual environment for the Python comparison tools:

```sh
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

On Linux and macOS, use `.venv/bin/python` instead of
`.\.venv\Scripts\python`.

Run the Python prototype directly:

```sh
python mid_simplify_v5.py --pd-code "PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]"
```

Use it as a Python API:

```python
import mid_simplify_v5 as simplify

code = simplify.parse_pd_code("PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]")
result = simplify.find_simplification(code, max_paths=100)
print(result.found)
```

Differentially test the C++ executable and the Python implementation:

```sh
.\.venv\Scripts\python tools\compare_cpp_python.py --include-reference
```

Compare runtime and peak RSS memory usage:

```sh
.\.venv\Scripts\python tools\benchmark_cpp_python.py
```

The latest local comparison summary is in
[Python and C++ Comparison](docs/python-cpp-comparison.md).

## Library Use

```cpp
#include "pdcode_simplify/pdcode_simplify.hpp"

auto code = pdcode_simplify::parse_pd_code("[(0, 1, 2, 3), (2, 3, 0, 1)]");
auto components = pdcode_simplify::analyze_components(code);
auto result = pdcode_simplify::find_simplification(code);
if (result.found) {
    // result.red_path and result.green_path describe the witness.
}
```

The library also includes deterministic test helpers for Reidemeister I/II
stress tests:

```cpp
pdcode_simplify::RandomInflationOptions options;
options.moves = 18;
options.seed = 101;

auto inflated = pdcode_simplify::randomly_increase_crossings(code, options);
auto simplified = pdcode_simplify::simplify_reidemeister_i_ii(inflated.code);
```

The randomized generator applies crossing-increasing inverse Reidemeister I
and II moves. The simplifier then repeatedly applies Reidemeister I and II
reductions while preserving the explicit count of crossingless components.

## Notes

PD labels are parsed as integers and each label must appear exactly twice.
The search can be bounded with `--max-paths`; use `--max-paths -1` to remove
that cap.

The test suite includes trefoil, figure-eight, and cinquefoil fixtures. Each
fixture is randomly inflated with multiple seeds and then reduced back to its
original crossing count with Reidemeister I/II simplification.
