#!/usr/bin/env python3
"""Smoke tests for the source-embedded Python C++ interface package."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = ROOT / "python_project" / "cpp-pd-code-simplify-interface"
sys.path.insert(0, str(INTERFACE_ROOT))

import cpp_pd_code_simplify_interface as interface  # noqa: E402


TREFOIL = "PD[X[1,5,2,4],X[3,1,4,6],X[5,3,6,2]]"


def main() -> int:
    if "CPP_PD_CODE_SIMPLIFY_INTERFACE_CACHE_DIR" not in os.environ:
        os.environ["CPP_PD_CODE_SIMPLIFY_INTERFACE_CACHE_DIR"] = str(ROOT / ".cache" / "python-interface")

    library = interface.compile_simplifier(force=True)
    assert library.exists(), library

    trefoil = interface.simplify(TREFOIL)
    assert trefoil["simplification_found"] is False
    assert trefoil["input_components"]["total_components"] == 1
    assert trefoil["path_search_mode"] == "heuristic"

    unknot = interface.simplify("PD[]")
    assert unknot["input_components"]["crossingless_components"] == 1
    assert unknot["path_search_mode"] == "heuristic"

    kink = interface.simplify("PD[X[0,0,1,1]]")
    assert kink["pd_simplification"]["reidemeister_i_moves"] == 1
    assert kink["search_components"]["crossingless_components"] == 1
    assert kink["path_search_mode"] == "heuristic"

    brute = interface.simplify(TREFOIL, ban_heuristic=True)
    assert brute["path_search_mode"] == "bruteforce"

    batch = interface.simplify_many([TREFOIL, "PD[]"])
    assert len(batch) == 2
    assert batch[0]["input_components"]["total_components"] == 1
    assert batch[1]["input_components"]["crossingless_components"] == 1

    print("Python C++ interface tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
