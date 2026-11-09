#!/usr/bin/env python3
"""Create a deterministic, SBOM-ish inventory for the developer preview.

This is intentionally a small JSON inventory rather than a claim of SPDX/CycloneDX
completeness.  It records the external components and their exact lock pins so a
consumer can audit what must be fetched separately; upstream applications are never
copied into the platform archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

try:  # Works both as ``python release/inventory.py`` and as a package import.
    from .validate_versions import default_lock_path, load_lock
except ImportError:  # pragma: no cover - exercised by the Makefile entry point.
    from validate_versions import default_lock_path, load_lock


EXTERNAL_COMPONENTS = {"phicad", "tscircuit"}
EXTERNAL_PARENT_DIRS = {"vendor", "vendors", "external", "upstream", "third_party", "third-party"}
VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _purl(component: Dict[str, Any]) -> str:
    version = component["version"]
    if component["ecosystem"] == "npm":
        return "pkg:npm/%s@%s" % (component["name"], version)
    source = component["source"].removesuffix(".git")
    owner_repo = source.rsplit("github.com/", 1)[-1]
    return "pkg:github/%s@%s" % (owner_repo, version)


def find_external_paths(root: Path) -> List[str]:
    """Find likely vendored component directories for reporting and exclusion."""
    found = set()
    for path in root.rglob("*"):
        if not path.is_dir() or path.is_symlink():
            continue
        parts = [part.lower() for part in path.relative_to(root).parts]
        if not parts:
            continue
        component_indexes = [i for i, part in enumerate(parts) if part in EXTERNAL_COMPONENTS]
        for index in component_indexes:
            if index > 0 and any(parent in EXTERNAL_PARENT_DIRS for parent in parts[:index]):
                found.add(str(path.relative_to(root)))
                break
    return sorted(found)


def build_inventory(root: Path, version: str, lock_path: Path | None = None) -> Dict[str, Any]:
    root = root.resolve()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("release version must be an exact semantic version: %s" % version)
    requested_lock = lock_path
    if requested_lock is not None and not requested_lock.is_absolute():
        requested_lock = root / requested_lock
    selected_lock = (requested_lock or default_lock_path(root)).resolve()
    lock = load_lock(selected_lock)
    lock_digest = _sha256(selected_lock)
    components = []
    for component in sorted(lock["components"], key=lambda item: item["name"].lower()):
        entry = {
            "bom_ref": _purl(component),
            "ecosystem": component["ecosystem"],
            "external": True,
            "name": component["name"],
            "pin": component["pin"],
            "source": component["source"],
            "version": component["version"],
            "vendored": False,
        }
        for optional_key in ("product_surface", "product_surfaces", "upstream", "additional_packages", "pull_request"):
            if optional_key in component:
                entry[optional_key] = component[optional_key]
        components.append(entry)

    return {
        "schema_version": 1,
        "inventory_type": "sbom-ish-component-inventory",
        "application": {
            "name": "PhiCad Platform",
            "version": version,
            "external_components_vendored": False,
        },
        "lock": {
            "path": str(selected_lock.relative_to(root)),
            "sha256": lock_digest,
        },
        "components": components,
        "vendored_component_paths": find_external_paths(root),
        "notes": [
            "PhiCad and tscircuit remain pinned external components.",
            "The lock pin is the authoritative fetch reference for this preview.",
        ],
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--version", default="0.1.0-dev.1")
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inventory = build_inventory(args.repo_root, args.version, args.lock)
    except (OSError, ValueError) as exc:
        print("component inventory: ERROR: %s" % exc, file=sys.stderr)
        return 1
    output = args.output if args.output.is_absolute() else args.repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Wrote %s" % output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
