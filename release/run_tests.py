#!/usr/bin/env python3
"""Run unit or MCP tests without making optional MCP tests a PR requirement."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def _unittest_fallback(root: Path) -> int:
    discovered = False
    for directory in (root / "release" / "tests", root / "tests", root / "test"):
        if not directory.is_dir():
            continue
        discovered = True
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(directory), "-p", "test_*.py"],
            cwd=root,
        )
        if result.returncode:
            return result.returncode
    if not discovered:
        print("No Python test directories found; unit tests skipped")
    return 0


def run(kind: str, root: Path) -> int:
    if kind not in {"unit", "mcp"}:
        raise ValueError("test kind must be unit or mcp")
    if _pytest_module_available(root):
        expression = "not mcp" if kind == "unit" else "mcp"
        test_paths = [str(root / "release" / "tests")]
        if kind == "unit":
            test_paths.extend(
                str(root / directory)
                for directory in ("tests/unit",)
                if (root / directory).is_dir()
            )
        elif (root / "tests/mcp").is_dir():
            test_paths.append(str(root / "tests/mcp"))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-m", expression, *test_paths],
            cwd=root,
        )
        if kind == "mcp" and result.returncode == 5:
            print("No MCP-marked tests found; MCP test stage skipped")
            return 0
        return result.returncode
    if kind == "mcp":
        print("pytest is not installed; no MCP tests were run")
        return 0
    return _unittest_fallback(root)


def _pytest_module_available(root: Path) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("unit", "mcp"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    return run(args.kind, args.root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
