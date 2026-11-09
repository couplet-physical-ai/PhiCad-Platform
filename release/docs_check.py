#!/usr/bin/env python3
"""Run the repository documentation build in strict mode when configured."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    config = next((root / name for name in ("mkdocs.yml", "mkdocs.yaml") if (root / name).is_file()), None)
    if config is None:
        print("No MkDocs configuration found; strict docs build skipped")
        return 0

    with tempfile.TemporaryDirectory(prefix="phicad-docs-") as temporary:
        command = [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "--clean",
            "--config-file",
            str(config),
            "--site-dir",
            str(Path(temporary) / "site"),
        ]
        result = subprocess.run(command, cwd=root)
    if result.returncode:
        return result.returncode
    print("Strict documentation build passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
