#!/usr/bin/env python3
"""Validate final C++ PD-code output with pd-code-to-diagram sanity."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List


ROOT = Path(__file__).resolve().parents[1]

CASES = [
    (
        "trefoil",
        "PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]",
    ),
    (
        "zero-based-trefoil",
        "PD[X[0,4,1,3],X[2,0,3,5],X[4,2,5,1]]",
    ),
    (
        "figure-eight",
        "PD[X[4,2,5,1],X[8,6,1,5],X[6,3,7,4],X[2,7,3,8]]",
    ),
    (
        "cinquefoil",
        "PD[X[8,0,1,9],X[0,2,3,1],X[2,4,5,3],X[4,6,7,5],X[6,8,9,7]]",
    ),
    (
        "orientation-repair-five-crossing",
        "PD[X[1,6,2,7],X[9,4,10,5],X[8,1,7,10],X[6,3,5,2],X[4,9,3,8]]",
    ),
]


def executable_suffix() -> str:
    return ".exe" if os.name == "nt" else ""


def find_executable() -> Path:
    override = os.environ.get("PD_SIMPLIFY_EXECUTABLE")
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates.append(ROOT / "build" / "bin" / ("pd_simplify" + executable_suffix()))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "pd_simplify executable was not found. Run `python tools/package.py test` "
        "or set PD_SIMPLIFY_EXECUTABLE."
    )


def configure_cpp_simple_interface() -> None:
    cxx = os.environ.get("CXX")
    if not cxx:
        return
    compiler = Path(cxx)
    if compiler.parent != Path("."):
        os.environ["PATH"] = str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")
    try:
        import cpp_simple_interface
    except ImportError:
        return
    cpp_simple_interface.set_gpp_filepath(cxx)


def import_pd_code_to_diagram():
    configure_cpp_simple_interface()
    try:
        import pd_code_to_diagram
    except ImportError as exc:
        raise RuntimeError(
            "pd-code-to-diagram is required for C++ output sanity tests. "
            "Install development dependencies with `python -m pip install -r requirements-dev.txt`."
        ) from exc
    return pd_code_to_diagram


def parse_pd_code(text: str) -> List[List[int]]:
    if text.strip().replace(" ", "") in {"PD[]", "[]"}:
        return []

    rows: List[List[int]] = []
    for block in re.findall(r"X\[(.*?)\]", text):
        values = [int(token) for token in re.findall(r"-?\d+", block)]
        if len(values) != 4:
            raise ValueError(f"invalid crossing in PD code: {block!r}")
        rows.append(values)
    if not rows:
        raise ValueError(f"could not parse PD code: {text!r}")
    return rows


def format_pd_code(code: List[List[int]]) -> str:
    return "PD[" + ",".join("X[{},{},{},{}]".format(*row) for row in code) + "]"


def run_cpp(executable: Path, pd_code: str) -> dict:
    proc = subprocess.run(
        [
            str(executable),
            "--pd-code",
            pd_code,
            "--reduction-round",
            "0",
            "--json",
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "C++ simplifier failed\n"
            f"command: {executable} --pd-code {pd_code!r} --reduction-round 0 --json\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    payload = json.loads(proc.stdout)
    if "final_pd_code" not in payload:
        raise RuntimeError(f"C++ JSON output did not contain final_pd_code: {payload}")
    return payload


def test_log_file(executable: Path) -> None:
    log_path = ROOT / ".cache" / "cpp-cli-log-file-test.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(executable),
            "--pd-code",
            "PD[X[1,5,2,4],X[2,5,3,6],X[6,3,1,4]]",
            "--max-thread",
            "1",
            "--verbose",
            "--show-step-pd",
            "--log-file",
            str(log_path),
        ],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"C++ log-file smoke failed:\n{proc.stdout}\n{proc.stderr}")
    log_text = log_path.read_text(encoding="utf-8")
    if "step_pd_code[1]: PD[X[1,2,2,1]]" not in log_text:
        raise AssertionError("C++ log file should contain stdout step output")
    if "final_pd_code: PD[]" not in log_text:
        raise AssertionError("C++ log file should contain stdout final output")
    if "[pdcode-simplify " not in log_text:
        raise AssertionError("C++ log file should contain stderr verbose output")


def main() -> int:
    pd_code_to_diagram = import_pd_code_to_diagram()
    executable = find_executable()

    for name, pd_code in CASES:
        payload = run_cpp(executable, pd_code)
        final_text = payload["final_pd_code"]
        final_code = parse_pd_code(final_text)
        diagram = pd_code_to_diagram.get_diagram_from_pd_code(final_code)
        round_tripped = pd_code_to_diagram.diagram_to_pd_code(diagram)
        if round_tripped != final_code:
            raise AssertionError(
                f"{name} final PD code changed after pd-code-to-diagram sanity\n"
                f"final:      {final_text}\n"
                f"round trip: {format_pd_code(round_tripped)}"
            )

    test_log_file(executable)
    print(f"C++ output diagram sanity tests passed ({len(CASES)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
