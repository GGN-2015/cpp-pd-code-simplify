#!/usr/bin/env python3
"""Compare C++ simplification against SnapPy/Spherogram-flavored fixtures.

The fixtures below are taken from Spherogram's doctests and link tests.  This
entry point intentionally runs only this project's C++ CLI executable
(``pd_simplify``) on our side.  It compares final crossing counts against the
corresponding Spherogram simplification result and writes a CSV with timing
data for both implementations.

Timing note: the C++ measurement is CLI wall time, so it includes process
startup and JSON parsing overhead.  The Spherogram measurement is in-process
wall time and excludes import startup.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = ROOT / ".cache" / "snappy_flavor_comparison.csv"


Crossing = tuple[int, int, int, int]


def pd_code(rows: Iterable[Crossing]) -> str:
    return "PD[" + ",".join("X[{},{},{},{}]".format(*row) for row in rows) + "]"


def parse_pd_code(text: str) -> list[Crossing]:
    rows: list[Crossing] = []
    for block in re.findall(r"X\[(.*?)\]", text):
        values = [int(token) for token in re.findall(r"-?\d+", block)]
        if len(values) != 4:
            raise ValueError(f"invalid crossing in PD code: {block!r}")
        rows.append((values[0], values[1], values[2], values[3]))
    if not rows and text.strip().replace(" ", "") not in {"PD[]", "[]"}:
        raise ValueError(f"could not parse PD code: {text!r}")
    return rows


@dataclass(frozen=True)
class SnappyFlavorCase:
    name: str
    pd: str
    expected_crossings: int
    source: str
    description: str
    snappy_mode: str = "global"
    slow: bool = False

    @property
    def input_crossings(self) -> int:
        return self.pd.count("X[")


@dataclass
class TimedResult:
    payload: dict[str, object]
    timings: list[float]
    returncode: int | None = None
    error: str = ""
    stderr: str = ""

    @property
    def mean_seconds(self) -> float:
        return statistics.mean(self.timings) if self.timings else 0.0

    @property
    def min_seconds(self) -> float:
        return min(self.timings) if self.timings else 0.0

    @property
    def max_seconds(self) -> float:
        return max(self.timings) if self.timings else 0.0


CASES: tuple[SnappyFlavorCase, ...] = (
    SnappyFlavorCase(
        name="spherogram_simplify_basic_7_to_4",
        pd=pd_code(
            [
                (13, 10, 14, 11),
                (11, 5, 12, 4),
                (3, 13, 4, 12),
                (9, 14, 10, 1),
                (1, 7, 2, 6),
                (2, 7, 3, 8),
                (5, 9, 6, 8),
            ]
        ),
        expected_crossings=4,
        source="Spherogram Link.simplify('basic') doctest",
        description="A one-component 7-crossing diagram that Spherogram reduces to 4 crossings with R1/R2 simplification.",
        snappy_mode="basic",
    ),
    SnappyFlavorCase(
        name="spherogram_untwist_square_knot_9_to_6",
        pd=pd_code(
            [
                (2, 0, 3, 17),
                (16, 2, 17, 1),
                (0, 16, 1, 15),
                (9, 6, 10, 7),
                (7, 10, 8, 11),
                (11, 8, 12, 9),
                (3, 15, 4, 14),
                (13, 5, 14, 4),
                (5, 13, 6, 12),
            ]
        ),
        expected_crossings=6,
        source="Spherogram untwist_diagram doctest via Link.simplify('global')",
        description="Opposite-handed trefoils connected with three extra twists; Spherogram removes 3 crossings.",
        snappy_mode="global",
    ),
    SnappyFlavorCase(
        name="spherogram_k14n2345_backtrack30_seed2_33_to_14",
        pd=pd_code(
            [
                (60, 2, 61, 1),
                (0, 54, 1, 53),
                (49, 65, 50, 64),
                (59, 46, 60, 47),
                (47, 54, 48, 55),
                (11, 50, 12, 51),
                (48, 13, 49, 14),
                (32, 42, 33, 41),
                (40, 16, 41, 15),
                (19, 39, 20, 38),
                (35, 23, 36, 22),
                (14, 34, 15, 33),
                (2, 32, 3, 31),
                (18, 6, 19, 5),
                (52, 52, 53, 51),
                (4, 26, 5, 25),
                (3, 28, 4, 29),
                (55, 42, 56, 43),
                (56, 46, 57, 45),
                (44, 58, 45, 57),
                (43, 58, 44, 59),
                (23, 63, 24, 62),
                (24, 61, 25, 62),
                (34, 8, 35, 7),
                (39, 6, 40, 7),
                (9, 9, 10, 8),
                (29, 31, 30, 30),
                (12, 65, 13, 0),
                (10, 64, 11, 63),
                (37, 21, 38, 20),
                (36, 21, 37, 22),
                (27, 17, 28, 16),
                (26, 17, 27, 18),
            ]
        ),
        expected_crossings=14,
        source="Spherogram Link.simplify('global') doctest, K14n2345.backtrack(30) with random.seed(2)",
        description="A deterministic fixture generated from the Spherogram K14n2345 global-simplify example.",
        snappy_mode="global",
        slow=True,
    ),
    SnappyFlavorCase(
        name="spherogram_unit_3_1_stays_3",
        pd=pd_code([(5, 2, 0, 3), (3, 0, 4, 1), (1, 4, 2, 5)]),
        expected_crossings=3,
        source="Spherogram links.test TestLinkFunctions.K3_1",
        description="Trefoil seed from Spherogram's knot invariant tests should remain a 3-crossing knot.",
        snappy_mode="basic",
    ),
    SnappyFlavorCase(
        name="spherogram_unit_7_2_stays_7",
        pd=pd_code(
            [
                (13, 10, 0, 11),
                (9, 0, 10, 1),
                (1, 8, 2, 9),
                (7, 2, 8, 3),
                (3, 6, 4, 7),
                (11, 4, 12, 5),
                (5, 12, 6, 13),
            ]
        ),
        expected_crossings=7,
        source="Spherogram links.test TestLinkFunctions.K7_2",
        description="K7_2 seed from Spherogram's knot invariant tests should remain a 7-crossing knot.",
        snappy_mode="basic",
    ),
    SnappyFlavorCase(
        name="spherogram_unit_8_3_stays_8",
        pd=pd_code(
            [
                (15, 11, 0, 10),
                (9, 1, 10, 0),
                (1, 9, 2, 8),
                (7, 3, 8, 2),
                (3, 14, 4, 15),
                (13, 4, 14, 5),
                (5, 12, 6, 13),
                (11, 6, 12, 7),
            ]
        ),
        expected_crossings=8,
        source="Spherogram links.test TestLinkFunctions.K8_3",
        description="K8_3 seed from Spherogram's knot invariant tests should remain an 8-crossing knot.",
        snappy_mode="basic",
    ),
    SnappyFlavorCase(
        name="spherogram_unit_8_13_stays_8",
        pd=pd_code(
            [
                (15, 6, 0, 7),
                (7, 0, 8, 1),
                (1, 13, 2, 12),
                (11, 3, 12, 2),
                (3, 11, 4, 10),
                (13, 5, 14, 4),
                (5, 8, 6, 9),
                (9, 15, 10, 14),
            ]
        ),
        expected_crossings=8,
        source="Spherogram links.test TestLinkFunctions.K8_13",
        description="K8_13 seed from Spherogram's knot invariant tests should remain an 8-crossing knot.",
        snappy_mode="basic",
    ),
)


CSV_FIELDS = [
    "case",
    "status",
    "source",
    "description",
    "snappy_mode",
    "input_crossings",
    "expected_crossings",
    "cpp_final_crossings",
    "snappy_final_crossings",
    "cpp_final_pd_code_crossings",
    "snappy_final_pd_code_crossings",
    "final_pd_code_crossing_delta",
    "cpp_final_components",
    "snappy_final_components",
    "cpp_simplification_found",
    "snappy_simplification_found",
    "cpp_mean_seconds",
    "snappy_mean_seconds",
    "time_delta_mean_seconds",
    "cpp_over_snappy_mean_ratio",
    "cpp_min_seconds",
    "snappy_min_seconds",
    "cpp_max_seconds",
    "snappy_max_seconds",
    "repeat",
    "cpp_returncode",
    "cpp_timed_out",
    "cpp_resource_limited",
    "cpp_error",
    "snappy_error",
    "cpp_final_pd_code",
    "snappy_final_pd_code",
]


def executable_suffix() -> str:
    return ".exe" if os.name == "nt" else ""


def find_executable(override: str | None) -> Path:
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    env_override = os.environ.get("PD_SIMPLIFY_EXECUTABLE")
    if env_override:
        candidates.append(Path(env_override))
    candidates.extend(
        [
            ROOT / "build" / "bin" / ("pd_simplify" + executable_suffix()),
            ROOT / "build-manual" / ("pd_simplify" + executable_suffix()),
            ROOT / "build" / ("pd_simplify" + executable_suffix()),
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    found = shutil.which("pd_simplify")
    if found:
        return Path(found)

    raise FileNotFoundError(
        "pd_simplify executable was not found. Run `python tools/package.py build`, "
        "pass --cpp-exe, or set PD_SIMPLIFY_EXECUTABLE."
    )


def one_result(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return payload[0]
    raise TypeError(f"unexpected JSON payload from pd_simplify: {payload!r}")


def command_for_case(executable: Path, case: SnappyFlavorCase, args: argparse.Namespace) -> list[str]:
    command = [
        str(executable),
        "--pd-code",
        case.pd,
        "--json",
        "--max-paths",
        str(args.max_paths),
        "--reduction-round",
        str(args.reduction_round),
        "--max-thread",
        str(args.max_thread),
        "--bruteforce-budget",
        str(args.bruteforce_budget),
    ]
    if args.timeout is not None:
        command.extend(["--timeout", str(args.timeout)])
    if args.ban_heuristic:
        command.append("--ban-heuristic")
    if args.reapr:
        command.append("--reapr")
    if args.quit_at_expected and case.input_crossings > case.expected_crossings:
        command.extend(["--quit-at-crossing", str(case.expected_crossings)])
    return command


def run_cpp_case(executable: Path, case: SnappyFlavorCase, args: argparse.Namespace) -> TimedResult:
    command = command_for_case(executable, case, args)
    timings: list[float] = []
    payload: dict[str, object] = {}
    returncode: int | None = None
    stderr = ""

    for _ in range(args.repeat):
        if args.show_commands:
            print("+ " + " ".join(command), file=sys.stderr)
        started = time.perf_counter()
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        returncode = proc.returncode
        stderr = proc.stderr
        if proc.returncode not in (0, 1, 2):
            return TimedResult(
                payload=payload,
                timings=timings,
                returncode=returncode,
                stderr=stderr,
                error=f"pd_simplify exited with {proc.returncode}",
            )
        try:
            payload = one_result(json.loads(proc.stdout))
        except Exception as exc:
            return TimedResult(
                payload=payload,
                timings=timings,
                returncode=returncode,
                stderr=stderr,
                error=f"could not parse pd_simplify JSON output: {exc}",
            )
        if payload.get("error") or payload.get("timed_out") or payload.get("resource_limited"):
            break

    return TimedResult(payload=payload, timings=timings, returncode=returncode, stderr=stderr)


def run_snappy_case(case: SnappyFlavorCase, args: argparse.Namespace) -> TimedResult:
    try:
        from spherogram import Link
    except ImportError as exc:
        return TimedResult(
            payload={},
            timings=[],
            error=(
                "Spherogram/SnapPy is required for comparison. "
                "Install snappy or spherogram before running this script."
            ),
            stderr=str(exc),
        )

    rows = parse_pd_code(case.pd)
    timings: list[float] = []
    payload: dict[str, object] = {}
    for _ in range(args.repeat):
        random.seed(args.snappy_seed)
        started = time.perf_counter()
        link = Link(list(rows))
        simplified = link.simplify(case.snappy_mode)
        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        payload = {
            "simplification_found": bool(simplified),
            "final_crossings": len(link.crossings),
            "final_components": {"total_components": len(link.link_components)},
            "final_pd_code": pd_code(link.PD_code()),
        }
    return TimedResult(payload=payload, timings=timings)


def component_count(payload: dict[str, object]) -> object:
    components = payload.get("final_components")
    if isinstance(components, dict):
        return components.get("total_components")
    return ""


def final_pd_code_crossing_count(payload: dict[str, object]) -> object:
    final_pd_code = payload.get("final_pd_code")
    if not isinstance(final_pd_code, str):
        return ""
    try:
        return len(parse_pd_code(final_pd_code))
    except ValueError:
        return ""


def ratio(numerator: float, denominator: float) -> str:
    if denominator == 0:
        return ""
    return f"{numerator / denominator:.9f}"


def seconds(value: float) -> str:
    return f"{value:.9f}"


def status_for(case: SnappyFlavorCase, cpp: TimedResult, snappy: TimedResult) -> tuple[str, str, str]:
    cpp_error = cpp.error or str(cpp.payload.get("error") or "")
    snappy_error = snappy.error or str(snappy.payload.get("error") or "")
    failures: list[str] = []

    if cpp_error:
        failures.append(f"C++ error: {cpp_error}")
    if snappy_error:
        failures.append(f"Spherogram error: {snappy_error}")
    if cpp.payload.get("timed_out"):
        failures.append("C++ timed out")
    if cpp.payload.get("resource_limited"):
        failures.append("C++ resource limited")

    cpp_crossings = cpp.payload.get("final_crossings")
    snappy_crossings = snappy.payload.get("final_crossings")
    cpp_pd_crossings = final_pd_code_crossing_count(cpp.payload)
    snappy_pd_crossings = final_pd_code_crossing_count(snappy.payload)
    if cpp_crossings != case.expected_crossings:
        failures.append(f"C++ final_crossings={cpp_crossings}, expected {case.expected_crossings}")
    if snappy_crossings != case.expected_crossings:
        failures.append(f"Spherogram final_crossings={snappy_crossings}, expected {case.expected_crossings}")
    if cpp_pd_crossings != case.expected_crossings:
        failures.append(
            f"C++ final_pd_code has {cpp_pd_crossings} crossings, expected {case.expected_crossings}"
        )
    if snappy_pd_crossings != case.expected_crossings:
        failures.append(
            f"Spherogram final_pd_code has {snappy_pd_crossings} crossings, expected {case.expected_crossings}"
        )
    if cpp_pd_crossings != "" and snappy_pd_crossings != "" and cpp_pd_crossings != snappy_pd_crossings:
        failures.append(
            f"final_pd_code crossing mismatch: C++={cpp_pd_crossings}, Spherogram={snappy_pd_crossings}"
        )

    cpp_components = component_count(cpp.payload)
    snappy_components = component_count(snappy.payload)
    if cpp_components not in ("", 1):
        failures.append(f"C++ final_components={cpp_components}, expected 1")
    if snappy_components not in ("", 1):
        failures.append(f"Spherogram final_components={snappy_components}, expected 1")

    status = "ok" if not failures else "fail"
    return status, cpp_error, snappy_error or "; ".join(failures)


def compare_case(
    executable: Path,
    case: SnappyFlavorCase,
    args: argparse.Namespace,
) -> dict[str, object]:
    cpp = run_cpp_case(executable, case, args)
    snappy = run_snappy_case(case, args)
    status, cpp_error, snappy_error = status_for(case, cpp, snappy)
    delta = cpp.mean_seconds - snappy.mean_seconds
    cpp_pd_crossings = final_pd_code_crossing_count(cpp.payload)
    snappy_pd_crossings = final_pd_code_crossing_count(snappy.payload)
    pd_crossing_delta = ""
    if isinstance(cpp_pd_crossings, int) and isinstance(snappy_pd_crossings, int):
        pd_crossing_delta = cpp_pd_crossings - snappy_pd_crossings
    return {
        "case": case.name,
        "status": status,
        "source": case.source,
        "description": case.description,
        "snappy_mode": case.snappy_mode,
        "input_crossings": case.input_crossings,
        "expected_crossings": case.expected_crossings,
        "cpp_final_crossings": cpp.payload.get("final_crossings", ""),
        "snappy_final_crossings": snappy.payload.get("final_crossings", ""),
        "cpp_final_pd_code_crossings": cpp_pd_crossings,
        "snappy_final_pd_code_crossings": snappy_pd_crossings,
        "final_pd_code_crossing_delta": pd_crossing_delta,
        "cpp_final_components": component_count(cpp.payload),
        "snappy_final_components": component_count(snappy.payload),
        "cpp_simplification_found": cpp.payload.get("simplification_found", ""),
        "snappy_simplification_found": snappy.payload.get("simplification_found", ""),
        "cpp_mean_seconds": seconds(cpp.mean_seconds),
        "snappy_mean_seconds": seconds(snappy.mean_seconds),
        "time_delta_mean_seconds": seconds(delta),
        "cpp_over_snappy_mean_ratio": ratio(cpp.mean_seconds, snappy.mean_seconds),
        "cpp_min_seconds": seconds(cpp.min_seconds),
        "snappy_min_seconds": seconds(snappy.min_seconds),
        "cpp_max_seconds": seconds(cpp.max_seconds),
        "snappy_max_seconds": seconds(snappy.max_seconds),
        "repeat": len(cpp.timings),
        "cpp_returncode": "" if cpp.returncode is None else cpp.returncode,
        "cpp_timed_out": cpp.payload.get("timed_out", ""),
        "cpp_resource_limited": cpp.payload.get("resource_limited", ""),
        "cpp_error": cpp_error,
        "snappy_error": snappy_error,
        "cpp_final_pd_code": cpp.payload.get("final_pd_code", ""),
        "snappy_final_pd_code": snappy.payload.get("final_pd_code", ""),
    }


def selected_cases(args: argparse.Namespace) -> tuple[SnappyFlavorCase, ...]:
    cases = CASES
    if args.skip_slow:
        cases = tuple(case for case in cases if not case.slow)
    if args.case:
        names = set(args.case)
        available = {case.name for case in cases}
        missing = sorted(names - available)
        if missing:
            raise ValueError(f"unknown case(s): {', '.join(missing)}")
        cases = tuple(case for case in cases if case.name in names)
    return cases


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp-exe", help="path to pd_simplify executable")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help=f"comparison CSV output path; default {DEFAULT_CSV}")
    parser.add_argument("--case", action="append", help="run only the named case; may be repeated")
    parser.add_argument("--list", action="store_true", help="list available SnapPy-flavor cases and exit")
    parser.add_argument("--skip-slow", action="store_true", help="skip larger fixtures such as K14n2345.backtrack(30)")
    parser.add_argument("--keep-going", action="store_true", help="continue after a failed case")
    parser.add_argument("--show-commands", action="store_true", help="print each pd_simplify command before running it")
    parser.add_argument("--repeat", type=int, default=1, help="number of timing runs per case; default 1")
    parser.add_argument("--snappy-seed", type=int, default=0, help="random seed used before each Spherogram run")
    parser.add_argument(
        "--quit-at-expected",
        action="store_true",
        help="pass --quit-at-crossing for cases whose SnapPy target has fewer crossings than the input",
    )
    parser.add_argument("--max-paths", type=int, default=-1)
    parser.add_argument("--reduction-round", type=int, default=-1)
    parser.add_argument("--max-thread", type=int, default=-1)
    parser.add_argument("--bruteforce-budget", type=int, default=200000)
    parser.add_argument("--timeout", type=int, default=None, help="per-case pd_simplify timeout in seconds")
    parser.add_argument("--ban-heuristic", action="store_true")
    parser.add_argument("--reapr", action="store_true", help="also enable the experimental REAPR oracle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    if args.timeout is not None and (args.timeout < -1 or args.timeout == 0):
        parser.error("--timeout must be -1 or a positive integer")

    cases = selected_cases(args)
    if args.list:
        for case in cases:
            marker = " [slow]" if case.slow else ""
            print(f"{case.name}{marker}: expect {case.expected_crossings} crossings")
            print(f"  Spherogram mode: {case.snappy_mode}")
            print(f"  source: {case.source}")
            print(f"  {case.description}")
        return 0

    executable = find_executable(args.cpp_exe)
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    for case in cases:
        row = compare_case(executable, case, args)
        rows.append(row)
        if row["status"] == "ok":
            print(
                f"[OK] {case.name}: C++={row['cpp_mean_seconds']}s "
                f"Spherogram={row['snappy_mean_seconds']}s "
                f"ratio={row['cpp_over_snappy_mean_ratio']}"
            )
        else:
            failures.append(case.name)
            print(f"[FAIL] {case.name}: {row['snappy_error'] or row['cpp_error']}", file=sys.stderr)
            if not args.keep_going:
                break

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = ROOT / csv_path
    write_csv(csv_path, rows)
    print(f"Wrote comparison CSV: {csv_path}")

    if failures:
        print(f"{len(failures)} SnapPy-flavor case(s) failed: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(f"SnapPy-flavor C++ vs Spherogram comparison passed ({len(rows)} cases).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
