#!/usr/bin/env python3
"""Build twice with fixed inputs and prove the release artifacts are byte-identical."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

try:
    from .package import build_release, source_date_epoch
except ImportError:  # pragma: no cover - exercised by the Makefile entry point.
    from package import build_release, source_date_epoch


def verify(repo_root: Path, version: str, epoch: Optional[int] = None) -> None:
    root = repo_root.resolve()
    fixed_epoch = source_date_epoch(root, epoch)
    with tempfile.TemporaryDirectory(prefix="phicad-reproducibility-") as temporary:
        base = Path(temporary)
        first = build_release(root, base / "one", version, fixed_epoch)
        second = build_release(root, base / "two", version, fixed_epoch)
        names = ("archive", "checksum", "manifest", "inventory")
        for name in names:
            first_bytes = first[name].read_bytes()
            second_bytes = second[name].read_bytes()
            if first_bytes != second_bytes:
                raise ValueError("non-reproducible %s artifact" % name)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--version", default=os.environ.get("RELEASE_VERSION", "0.1.0-dev.1"))
    parser.add_argument("--source-date-epoch", type=int)
    args = parser.parse_args(argv)
    try:
        verify(args.repo_root, args.version, args.source_date_epoch)
    except (OSError, ValueError) as exc:
        print("reproducibility check: ERROR: %s" % exc, file=sys.stderr)
        return 1
    print("Reproducibility check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
