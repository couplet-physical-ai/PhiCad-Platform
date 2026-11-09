#!/usr/bin/env python3
"""Smoke-test installation in an isolated virtual environment when metadata exists."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    install_tests = root / "tests" / "install"
    if install_tests.is_dir() and _pytest_available():
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(install_tests)], cwd=root)
        if result.returncode:
            return result.returncode
    elif install_tests.is_dir():
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(install_tests), "-p", "test_*.py"],
            cwd=root,
        )
        if result.returncode:
            return result.returncode

    metadata = any((root / name).is_file() for name in ("pyproject.toml", "setup.py", "setup.cfg"))
    if not metadata:
        print("No Python packaging metadata found; isolated install skipped")
        return 0

    with tempfile.TemporaryDirectory(prefix="phicad-install-test-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command = [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            str(root),
        ]
        environment_variables = os.environ.copy()
        environment_variables.update(
            {
                "PIP_CONFIG_FILE": os.devnull,
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INPUT": "1",
            }
        )
        result = subprocess.run(command, cwd=root, env=environment_variables)
        if result.returncode:
            print("isolated install failed", file=sys.stderr)
            return result.returncode
        installed = subprocess.run(
            [str(python), "-m", "pip", "list", "--format=freeze"],
            cwd=root,
            stdout=subprocess.DEVNULL,
        )
        if installed.returncode:
            return installed.returncode
    print("Install tests passed")
    return 0


def _pytest_available() -> bool:
    result = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
