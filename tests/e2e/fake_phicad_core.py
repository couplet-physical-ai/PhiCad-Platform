#!/usr/bin/env python3
"""Tiny deterministic stand-in for the pinned PhiCad core used by e2e tests.

It deliberately implements only the JSON contract consumed by scripts/demo/v1_demo.py.  No real
CAD work is implied by this fake; it exists so the capture and evidence plumbing is testable on a
machine without Bun, Circuit Engine, or PhiCad's kicad-cli.
"""
from __future__ import annotations

import json
import sys

CIRCUIT = {
    "elements": 12,
    "components": 2,
    "pads": 4,
    "traces": 2,
    "vias": 0,
    "nets": 2,
    "width_mm": 18,
    "height_mm": 12,
}


def main() -> int:
    args = sys.argv[1:]
    if args == ["--version"]:
        print("fake-phicad-core 0.1.0")
        return 0
    if len(args) >= 3 and args[0] in {"check", "build"} and args[-1] == "--json":
        if args[0] == "check":
            print(json.dumps({"ok": True, "circuit": CIRCUIT, "findings": []}, sort_keys=True))
        else:
            print(json.dumps({
                "ok": True,
                "engine": {"ok": True, "findings": []},
                "verification": {
                    "ok": True,
                    "skipped": False,
                    "board": "fake-board.kicad_pcb",
                    "findings": [],
                },
                "circuit": CIRCUIT,
            }, sort_keys=True))
        return 0
    print("fake core: unsupported arguments", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
