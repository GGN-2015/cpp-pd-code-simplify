# cpp-pd-code-simplify

A small, dependency-free C++14 project for finding mid-simplification
witnesses in knot and link planar diagram codes.

The implementation follows the algorithmic structure of the local research
prototype:

- build oriented crossing entries from a PD code;
- build the dual graph of diagram faces;
- enumerate candidate red boundary paths;
- search shorter green paths in the dual graph;
- validate over/under consistency for the candidate disk.

The Python prototype is intentionally not part of this repository.

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
pd_simplify --max-paths 100 "[(0, 1, 2, 3), (2, 3, 0, 1)]"
```

Input may also be read from a file or standard input:

```sh
pd_simplify --input diagram.pd --json
```

The process exits with code `0` when a witness is found, `1` when no witness
is found, and `2` for invalid input or runtime errors.

## Library Use

```cpp
#include "pdcode_simplify/pdcode_simplify.hpp"

auto code = pdcode_simplify::parse_pd_code("[(0, 1, 2, 3), (2, 3, 0, 1)]");
auto result = pdcode_simplify::find_simplification(code);
if (result.found) {
    // result.red_path and result.green_path describe the witness.
}
```

## Notes

PD labels are parsed as integers and each label must appear exactly twice.
The search can be bounded with `--max-paths`; use `--max-paths -1` to remove
that cap.
