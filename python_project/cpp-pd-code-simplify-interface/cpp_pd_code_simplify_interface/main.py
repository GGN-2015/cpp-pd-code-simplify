from __future__ import annotations

import argparse
import ast
import contextlib
import ctypes
import hashlib
import json
import os
import pathlib
import platform
import re
import shlex
import struct
import sys
from importlib import resources
from typing import Any, Optional, Sequence, Union

import cpp_simple_interface


PdInput = Union[str, Sequence[Sequence[int]]]
PdManyInput = Union[str, Sequence[PdInput]]


class PdCodeSimplifyInterfaceError(RuntimeError):
    """Raised when the C++ dynamic library cannot be built or called."""


def _format_pd(crossings: Sequence[Sequence[int]]) -> str:
    parts = []
    for crossing in crossings:
        values = list(crossing)
        if len(values) != 4:
            raise ValueError(f"PD crossing must have four entries: {crossing!r}")
        parts.append("X[{},{},{},{}]".format(*(int(value) for value in values)))
    return "PD[" + ",".join(parts) + "]"


def _parse_x_crossings(text: str) -> Optional[list[list[int]]]:
    pattern = r"X\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\]"
    crossings = []
    for match in re.finditer(pattern, text):
        crossings.append([int(match.group(i)) for i in range(1, 5)])
    return crossings if crossings else None


def _as_crossings(pd_code: PdInput) -> list[list[int]]:
    if isinstance(pd_code, str):
        body = pd_code.strip()
        if ":" in body:
            body = body.split(":", 1)[1].strip()
        if body.replace(" ", "") in ("PD[]", "[]"):
            return []

        parsed = _parse_x_crossings(body)
        if parsed is not None:
            return parsed

        try:
            value = ast.literal_eval(body)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"unsupported PD-code string format: {pd_code!r}") from exc
    else:
        value = pd_code

    crossings = []
    for crossing in value:
        values = list(crossing)
        if len(values) != 4:
            raise ValueError(f"PD crossing must have four entries: {crossing!r}")
        crossings.append([int(item) for item in values])
    return crossings


def normalize_pd_code(pd_code: PdInput) -> str:
    """Normalize a supported PD-code value into standard ``PD[X[...],...]`` text."""

    return _format_pd(_as_crossings(pd_code))


def normalize_pd_codes(pd_codes: PdManyInput) -> list[str]:
    """Normalize one or more PD codes into standard ``PD[X[...],...]`` strings."""

    if isinstance(pd_codes, str):
        return [line.strip() for line in pd_codes.splitlines() if line.strip()]
    return [normalize_pd_code(pd_code) for pd_code in pd_codes]


@contextlib.contextmanager
def _resource_paths():
    package = "cpp_pd_code_simplify_interface"
    resource_names = [
        resources.files(package) / "data" / "src" / "pdcode_simplify.cpp",
        resources.files(package) / "data" / "src" / "native_interface.cpp",
        resources.files(package) / "data" / "include" / "pdcode_simplify" / "pdcode_simplify.hpp",
    ]

    contexts = []
    paths: list[pathlib.Path] = []
    try:
        for resource in resource_names:
            context = resources.as_file(resource)
            contexts.append(context)
            path = pathlib.Path(context.__enter__())
            if not path.exists():
                break
            paths.append(path)
        if len(paths) == len(resource_names):
            yield paths
            return
    except FileNotFoundError:
        pass
    finally:
        while contexts:
            contexts.pop().__exit__(None, None, None)

    current = pathlib.Path(__file__).resolve()
    for parent in current.parents:
        candidate_cpp = parent / "src" / "pdcode_simplify.cpp"
        candidate_wrapper = (
            parent
            / "python_project"
            / "cpp-pd-code-simplify-interface"
            / "cpp_pd_code_simplify_interface"
            / "data"
            / "src"
            / "native_interface.cpp"
        )
        candidate_header = parent / "include" / "pdcode_simplify" / "pdcode_simplify.hpp"
        if candidate_cpp.exists() and candidate_wrapper.exists() and candidate_header.exists():
            yield [candidate_cpp, candidate_wrapper, candidate_header]
            return

    raise PdCodeSimplifyInterfaceError(
        "cpp-pd-code-simplify C++ sources were not found. Installed wheels "
        "include them under cpp_pd_code_simplify_interface/data; editable "
        "checkouts use the repository root src/ and include/ directories."
    )


def _cache_dir() -> pathlib.Path:
    env_value = os.environ.get("CPP_PD_CODE_SIMPLIFY_INTERFACE_CACHE_DIR")
    if env_value:
        root = pathlib.Path(env_value)
    elif sys.platform == "win32":
        root = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "cpp-pd-code-simplify-interface"
    elif sys.platform == "darwin":
        root = pathlib.Path.home() / "Library" / "Caches" / "cpp-pd-code-simplify-interface"
    else:
        root = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "cpp-pd-code-simplify-interface"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _library_suffix() -> str:
    if platform.system() == "Windows":
        return ".dll"
    if platform.system() == "Darwin":
        return ".dylib"
    return ".so"


def _default_compile_flags(include_dir: pathlib.Path, library_path: pathlib.Path) -> list[str]:
    flags = ["-std=c++14", "-O3", "-DNDEBUG", "-I" + str(include_dir)]
    if platform.system() != "Windows":
        flags.append("-fPIC")
    if platform.system() == "Darwin":
        flags.extend(["-dynamiclib", "-install_name", "@rpath/" + library_path.name])
    else:
        flags.append("-shared")
    native = os.environ.get("CPP_PD_CODE_SIMPLIFY_INTERFACE_NATIVE", "1").strip().lower()
    if native not in ("0", "false", "no", "off"):
        flags.append("-march=native")
    extra = os.environ.get("CPP_PD_CODE_SIMPLIFY_INTERFACE_CXXFLAGS", "").strip()
    if extra:
        flags.extend(shlex.split(extra))
    return flags


def _cache_key(source_bytes: bytes, flags: Sequence[str]) -> str:
    digest = hashlib.sha256()
    digest.update(source_bytes)
    digest.update("\0".join(flags).encode("utf-8"))
    digest.update(cpp_simple_interface.get_gpp_filepath().encode("utf-8"))
    digest.update(platform.platform().encode("utf-8"))
    return digest.hexdigest()[:20]


def _compiler_runtime_path_entries() -> list[pathlib.Path]:
    compiler = cpp_simple_interface.get_gpp_filepath().strip()
    if not compiler:
        return []

    candidates = []
    unquoted = compiler
    if len(unquoted) >= 2 and unquoted[0] == unquoted[-1] and unquoted[0] in ("'", '"'):
        unquoted = unquoted[1:-1]
    candidates.append(unquoted)

    try:
        candidates.extend(shlex.split(compiler, posix=True))
    except ValueError:
        pass

    paths: list[pathlib.Path] = []
    for candidate in candidates:
        path = pathlib.Path(candidate)
        if path.exists() and path.is_file() and path.parent not in paths:
            paths.append(path.parent)
    return paths


def _pe_machine_bits(path: pathlib.Path) -> Optional[int]:
    if platform.system() != "Windows":
        return None
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if len(data) < pe_offset + 6 or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        return None
    machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
    if machine == 0x014C:
        return 32
    if machine in (0x8664, 0xAA64):
        return 64
    return None


def _validate_library_architecture(path: pathlib.Path) -> None:
    bits = _pe_machine_bits(path)
    if bits is None:
        return
    python_bits = struct.calcsize("P") * 8
    if bits != python_bits:
        raise PdCodeSimplifyInterfaceError(
            f"cached library is {bits}-bit but Python is {python_bits}-bit. "
            "Set CXX to a compiler whose target architecture matches Python, "
            "then delete the interface cache or call compile_simplifier(force=True)."
        )


def compile_simplifier(
    *,
    force: bool = False,
    cxx: Optional[str] = None,
    extra_flags: Optional[Sequence[str]] = None,
) -> pathlib.Path:
    """Compile the packaged C++ source as a cached dynamic library."""

    if cxx:
        cpp_simple_interface.set_gpp_filepath(cxx)

    with _resource_paths() as paths:
        pd_source, wrapper_source, header = paths
        include_dir = header.parents[1]
        source_bytes = pd_source.read_bytes() + b"\0" + wrapper_source.read_bytes() + b"\0" + header.read_bytes()

        cache = _cache_dir()
        placeholder = cache / ("pdcode-simplify-placeholder" + _library_suffix())
        flags = _default_compile_flags(include_dir, placeholder)
        if extra_flags:
            flags.extend(str(flag) for flag in extra_flags)
        library = cache / f"pdcode-simplify-{_cache_key(source_bytes, flags)}{_library_suffix()}"
        flags = _default_compile_flags(include_dir, library)
        if extra_flags:
            flags.extend(str(flag) for flag in extra_flags)

        if library.exists() and not force:
            return library

        tmp_library = cache / f"{library.name}.tmp-{os.getpid()}{_library_suffix()}"
        if tmp_library.exists():
            tmp_library.unlink()

        success, message = cpp_simple_interface.compile_cpp_files(
            [str(pd_source), str(wrapper_source)],
            str(tmp_library),
            other_flags=flags,
        )
        if not success and "-march=native" in flags:
            fallback_flags = [flag for flag in flags if flag != "-march=native"]
            success, message = cpp_simple_interface.compile_cpp_files(
                [str(pd_source), str(wrapper_source)],
                str(tmp_library),
                other_flags=fallback_flags,
            )

        if not success:
            raise PdCodeSimplifyInterfaceError(message)
        if not tmp_library.exists():
            raise PdCodeSimplifyInterfaceError(f"compiled dynamic library was not created: {tmp_library}")
        os.replace(tmp_library, library)
        return library


def get_simplifier_library() -> pathlib.Path:
    """Return the cached dynamic library path, compiling it first when necessary."""

    return compile_simplifier()


def get_simplifier_executable() -> pathlib.Path:
    """Backward-compatible alias returning the cached dynamic library path."""

    return get_simplifier_library()


_LOADED_LIBRARY_PATH: Optional[pathlib.Path] = None
_LOADED_LIBRARY: Optional[ctypes.CDLL] = None
_DLL_DIRECTORY_HANDLES: list[Any] = []


def _prepare_dll_search_path(path: pathlib.Path) -> None:
    if platform.system() != "Windows" or not hasattr(os, "add_dll_directory"):
        return
    for directory in [path.parent, *_compiler_runtime_path_entries()]:
        try:
            handle = os.add_dll_directory(str(directory))
        except OSError:
            continue
        _DLL_DIRECTORY_HANDLES.append(handle)


def _load_library() -> ctypes.CDLL:
    global _LOADED_LIBRARY_PATH, _LOADED_LIBRARY
    path = compile_simplifier()
    if _LOADED_LIBRARY is not None and _LOADED_LIBRARY_PATH == path:
        return _LOADED_LIBRARY

    _validate_library_architecture(path)
    _prepare_dll_search_path(path)
    library = ctypes.CDLL(str(path))
    library.pdcode_simplify_run_json.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_ulonglong,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_ulonglong,
    ]
    library.pdcode_simplify_run_json.restype = ctypes.c_void_p
    library.pdcode_simplify_free_string.argtypes = [ctypes.c_void_p]
    library.pdcode_simplify_free_string.restype = None
    _LOADED_LIBRARY_PATH = path
    _LOADED_LIBRARY = library
    return library


def _run_one(
    pd_text: str,
    *,
    max_paths: int = 100,
    known_crossingless_components: int = 0,
    remove_crossings: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    library = _load_library()
    removed_count = 0 if remove_crossings is None else len(remove_crossings)
    removed_array = None
    if removed_count:
        removed_array = (ctypes.c_int * removed_count)(*(int(value) for value in remove_crossings or []))

    pointer = library.pdcode_simplify_run_json(
        pd_text.encode("utf-8"),
        int(max_paths),
        int(known_crossingless_components),
        removed_array,
        int(removed_count),
    )
    if not pointer:
        raise PdCodeSimplifyInterfaceError("C++ interface returned a null JSON pointer")
    try:
        text = ctypes.string_at(pointer).decode("utf-8")
    finally:
        library.pdcode_simplify_free_string(pointer)

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PdCodeSimplifyInterfaceError(f"invalid simplifier JSON output: {text!r}") from exc
    if isinstance(result, dict) and "error" in result:
        raise PdCodeSimplifyInterfaceError(str(result["error"]))
    return result


def simplify(
    pd_code: PdInput,
    *,
    max_paths: int = 100,
    known_crossingless_components: int = 0,
    remove_crossings: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    """Run the C++ simplifier for one PD code and return its JSON result."""

    return _run_one(
        normalize_pd_code(pd_code),
        max_paths=max_paths,
        known_crossingless_components=known_crossingless_components,
        remove_crossings=remove_crossings,
    )


def simplify_many(
    pd_codes: PdManyInput,
    *,
    max_paths: int = 100,
    known_crossingless_components: int = 0,
    remove_crossings: Optional[Sequence[int]] = None,
) -> list[dict[str, Any]]:
    """Run the C++ simplifier for one or more PD codes and return JSON results."""

    return [
        _run_one(
            pd_text,
            max_paths=max_paths,
            known_crossingless_components=known_crossingless_components,
            remove_crossings=remove_crossings,
        )
        for pd_text in normalize_pd_codes(pd_codes)
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run cpp-pd-code-simplify through the Python interface.")
    parser.add_argument("pd_code", nargs="?", help="PD code as PD[...] text or a Python-style list of crossings.")
    parser.add_argument("--pd-file", "-f", help="read one file containing one or more labelled PD-code lines")
    parser.add_argument("--max-paths", type=int, default=100)
    parser.add_argument("--known-crossingless-components", type=int, default=0)
    parser.add_argument("--remove-crossings", help="comma-separated zero-based crossing indices")
    args = parser.parse_args(argv)
    if args.pd_file and args.pd_code:
        parser.error("pass either a positional PD code or --pd-file, not both")
    if not args.pd_file and not args.pd_code:
        parser.error("a positional PD code or --pd-file is required")
    remove_crossings = None
    if args.remove_crossings:
        remove_crossings = [int(token) for token in re.findall(r"-?\d+", args.remove_crossings)]

    exit_code = 0
    if args.pd_file:
        lines = []
        for line in pathlib.Path(args.pd_file).read_text(encoding="utf-8").splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            payload = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
            lines.append(payload)
        batch_payload = []
        for line in lines:
            try:
                batch_payload.append(
                    simplify(
                        line,
                        max_paths=args.max_paths,
                        known_crossingless_components=args.known_crossingless_components,
                        remove_crossings=remove_crossings,
                    )
                )
            except Exception as exc:
                exit_code = 2
                batch_payload.append({"error": str(exc)})
        payload: Any = batch_payload
    else:
        payload = simplify(
            args.pd_code or "",
            max_paths=args.max_paths,
            known_crossingless_components=args.known_crossingless_components,
            remove_crossings=remove_crossings,
        )

    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
