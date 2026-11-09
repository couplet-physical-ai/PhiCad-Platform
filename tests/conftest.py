"""Always test this worktree, including focused release/unit collection.

A shared external venv may have an editable install of a different checkout.
Test collection must not silently validate that checkout instead of these files.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
