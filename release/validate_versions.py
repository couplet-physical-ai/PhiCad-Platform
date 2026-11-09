#!/usr/bin/env python3
"""Validate the exact external-component lock used by release packaging.

The platform ships integration code and references to upstream components, not copies
of those applications.  This small JSON lock is intentionally dependency-free so it
can run before any third-party package is installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

COMPONENTS = ("phicad", "tscircuit")
SEMVER_RE = re.compile(
    r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FLOATING_PIN_RE = re.compile(
    r"(^|[-_/])(main|master|develop|development|trunk|head|latest|next|nightly)($|[-_/])",
    re.IGNORECASE,
)


class LockError(ValueError):
    """A human-readable lock validation error."""


def _no_duplicate_keys(pairs: List[Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LockError("duplicate JSON key: %s" % key)
        result[key] = value
    return result


def default_lock_path(repo_root: Path) -> Path:
    """Prefer a repository lock, while supporting this release-owned fallback."""
    candidates = (repo_root / "versions.lock", repo_root / "release" / "versions.lock")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_lock(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle, object_pairs_hook=_no_duplicate_keys)
    except FileNotFoundError as exc:
        raise LockError("lock file does not exist: %s" % path) from exc
    except json.JSONDecodeError as exc:
        raise LockError("invalid JSON in %s: %s" % (path, exc)) from exc

    if not isinstance(data, dict):
        raise LockError("lock root must be a JSON object")
    if data.get("schema_version") != 1:
        raise LockError("schema_version must be exactly 1")
    components = data.get("components")
    if not isinstance(components, list) or not components:
        raise LockError("components must be a non-empty array")

    seen = set()
    for index, component in enumerate(components):
        _validate_component(component, index, seen)

    missing = sorted(set(COMPONENTS) - seen)
    if missing:
        raise LockError("required external component(s) missing: %s" % ", ".join(missing))
    return data


def _validate_component(component: Any, index: int, seen: set) -> None:
    if not isinstance(component, dict):
        raise LockError("components[%d] must be an object" % index)
    for field in ("name", "ecosystem", "source", "version", "pin", "vendored"):
        if field not in component:
            raise LockError("components[%d] is missing %s" % (index, field))

    name = component["name"]
    if not isinstance(name, str) or not name.strip():
        raise LockError("components[%d].name must be a non-empty string" % index)
    normalized_name = name.strip().lower()
    if normalized_name not in COMPONENTS:
        raise LockError(
            "components[%d].name must be one of %s (got %r)"
            % (index, ", ".join(COMPONENTS), name)
        )
    if normalized_name in seen:
        raise LockError("duplicate component: %s" % name)
    seen.add(normalized_name)

    for field in ("ecosystem", "source", "version", "pin"):
        value = component[field]
        if not isinstance(value, str) or not value.strip():
            raise LockError("components[%d].%s must be a non-empty string" % (index, field))

    source = component["source"]
    if not source.startswith(("https://", "http://")):
        raise LockError("components[%d].source must be an HTTPS/HTTP URL" % index)

    version = component["version"]
    if not SEMVER_RE.fullmatch(version):
        raise LockError(
            "components[%d].version must be an exact semantic version: %r" % (index, version)
        )

    pin = component["pin"]
    if FLOATING_PIN_RE.search(pin) or pin.startswith(("^", "~", ">", "<", "=")):
        raise LockError("components[%d].pin is floating or ranged: %r" % (index, pin))
    if not (COMMIT_RE.fullmatch(pin) or SEMVER_RE.fullmatch(pin)):
        raise LockError(
            "components[%d].pin must be an exact version tag or immutable commit SHA: %r"
            % (index, pin)
        )
    if pin.lstrip("v") != version.lstrip("v") and not COMMIT_RE.fullmatch(pin):
        raise LockError(
            "components[%d].pin must match version (or be a commit SHA)" % index
        )

    if component["vendored"] is not False:
        raise LockError("components[%d].vendored must be false" % index)

    if "sha256" in component and (
        not isinstance(component["sha256"], str) or not SHA256_RE.fullmatch(component["sha256"])
    ):
        raise LockError("components[%d].sha256 must be exactly 64 hex characters" % index)
    if "integrity" in component and (
        not isinstance(component["integrity"], str) or not component["integrity"].strip()
    ):
        raise LockError("components[%d].integrity must be a non-empty string" % index)


def validate_platform_lock(path: Path) -> Dict[str, Any]:
    """Validate the installer/platform lock when the repository provides it.

    The platform scaffold calls this file ``versions.lock.json`` and stores tools
    rather than fetch metadata.  It is still an exact lock: every tool version must
    be a concrete value, never a range or a branch.  The release-owned lock above
    remains the source of upstream URLs and vendoring policy.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle, object_pairs_hook=_no_duplicate_keys)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise LockError("invalid platform lock %s: %s" % (path, exc)) from exc
    if not isinstance(data, dict) or data.get("lock_schema_version") != 1:
        raise LockError("%s must have lock_schema_version 1" % path)
    tools = data.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise LockError("%s must contain a non-empty tools object" % path)
    native_roles = ("phicad",) if "phicad" in tools else ("phicad-studio", "phicad-verify")
    required_tools = {"tscircuit", *native_roles}
    missing = sorted(required_tools - set(tools))
    if missing:
        raise LockError("%s is missing exact tool pins: %s" % (path, ", ".join(missing)))
    native_records = [tools[name] for name in ("phicad", "phicad-studio", "phicad-verify") if name in tools]
    for record in native_records:
        if not isinstance(record, dict):
            raise LockError("native tool pin must be an object")
        for field in ("version", "source", "commit"):
            if record.get(field) != native_records[0].get(field):
                raise LockError("%s must pin native roles to one PhiCad %s" % (path, field))
    for name, record in tools.items():
        if not isinstance(record, dict) or not isinstance(record.get("version"), str):
            raise LockError("%s.tools.%s.version must be an exact string" % (path, name))
        version = record["version"]
        if not version.strip() or version.startswith(("^", "~", ">", "<", "=")):
            raise LockError("%s.tools.%s.version is floating or ranged" % (path, name))
        if not SEMVER_RE.fullmatch(version):
            raise LockError("%s.tools.%s.version is not an exact semantic version: %r" % (path, name, version))
    return data


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--print-json", action="store_true", help="print normalized release lock JSON")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    requested_lock = args.lock
    if requested_lock is not None and not requested_lock.is_absolute():
        requested_lock = root / requested_lock
    path = (requested_lock or default_lock_path(root)).resolve()
    try:
        if path.name == "versions.lock.json" and path.is_file():
            platform_data = validate_platform_lock(path)
            if args.print_json:
                print(json.dumps(platform_data, indent=2, sort_keys=True))
            else:
                print("Validated %s (platform tools: %s)" % (path, ", ".join(sorted(platform_data["tools"]))))
            return 0
        data = load_lock(path)
        platform_path = root / "versions.lock.json"
        platform_data = None
        if platform_path.is_file() and platform_path.resolve() != path:
            platform_data = validate_platform_lock(platform_path)
    except LockError as exc:
        print("versions.lock: ERROR: %s" % exc, file=sys.stderr)
        return 1

    if args.print_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        names = [component["name"] for component in data["components"]]
        print("Validated %s (%s)" % (path, ", ".join(names)))
        if platform_data is not None:
            print("Validated %s (platform tools: %s)" % (platform_path, ", ".join(sorted(platform_data["tools"]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
