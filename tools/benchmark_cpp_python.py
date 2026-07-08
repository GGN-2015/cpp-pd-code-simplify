#!/usr/bin/env python3
"""Compare runtime and peak RSS of the C++ and Python simplifiers."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import psutil

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

REFERENCE_PD = """PD[
X[15,7,16,6],X[7,15,8,14],X[18,61,19,0],X[20,12,21,11],
X[12,24,13,23],X[13,26,14,27],X[29,22,30,23],X[21,30,22,31],
X[28,33,29,34],X[5,36,6,37],X[8,36,9,35],X[34,27,35,28],
X[1,41,2,40],X[19,43,20,42],X[43,25,44,24],X[25,45,26,44],
X[16,45,17,46],X[37,46,38,47],X[48,39,49,40],X[0,50,1,49],
X[10,51,11,52],X[31,53,32,52],X[41,50,42,51],X[55,3,56,2],
X[54,9,55,10],X[53,33,54,32],X[3,57,4,56],X[57,5,58,4],
X[60,17,61,18],X[59,38,60,39],X[58,47,59,48]
]"""

CASES: Dict[str, str] = {
    "trefoil": "PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]",
    "figure-eight": "PD[X[8,3,1,4],X[2,6,3,5],X[6,2,7,1],X[4,7,5,8]]",
    "reference-31": REFERENCE_PD,
}


def default_cpp_exe() -> str:
    candidates = [
        ROOT / "build-manual" / "pd_simplify.exe",
        ROOT / "build-manual" / "pd_simplify",
        ROOT / "build" / "pd_simplify.exe",
        ROOT / "build" / "pd_simplify",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    found = shutil.which("pd_simplify")
    if found:
        return found
    raise FileNotFoundError("Could not find pd_simplify; pass --cpp-exe")


def rss_tree(process: psutil.Process) -> int:
    total = 0
    try:
        total += process.memory_info().rss
        for child in process.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    return total


def run_peak(command: List[str], sample_interval: float = 0.01) -> Tuple[float, float, int]:
    start = time.perf_counter()
    proc = psutil.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    peak = 0
    while proc.poll() is None:
        peak = max(peak, rss_tree(proc))
        time.sleep(sample_interval)
    peak = max(peak, rss_tree(proc))
    stdout, stderr = proc.communicate()
    elapsed = time.perf_counter() - start
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(command)}\n{stderr}\n{stdout}"
        )
    return elapsed, peak / (1024 * 1024), proc.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp-exe", default=None, help="path to pd_simplify executable")
    parser.add_argument("--max-paths", type=int, default=100)
    parser.add_argument("--case", action="append", choices=sorted(CASES), help="case to run; default runs all")
    parser.add_argument("--sample-interval", type=float, default=0.01)
    args = parser.parse_args(argv)

    cpp_exe = args.cpp_exe or default_cpp_exe()
    selected = args.case or list(CASES)

    rows: List[Tuple[str, str, float, float, int]] = []
    for name in selected:
        pd_text = CASES[name]
        commands = {
            "cpp": [cpp_exe, "--json", "--pd-code", pd_text, "--max-paths", str(args.max_paths)],
            "python": [
                PYTHON,
                str(ROOT / "mid_simplify_v5.py"),
                "--json",
                "--pd-code",
                pd_text,
                "--max-paths",
                str(args.max_paths),
            ],
        }
        for engine, command in commands.items():
            elapsed, peak_mib, return_code = run_peak(command, args.sample_interval)
            rows.append((name, engine, elapsed, peak_mib, return_code))
            print(
                f"{name:12s} {engine:6s} time={elapsed:8.3f}s "
                f"peak_rss={peak_mib:8.2f} MiB return={return_code}"
            )

    print("\nSummary")
    print("case,engine,time_seconds,peak_rss_mib,return_code")
    for row in rows:
        print(f"{row[0]},{row[1]},{row[2]:.6f},{row[3]:.3f},{row[4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
