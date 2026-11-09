#!/usr/bin/env python3
"""Safe, local-only installer for the PhiCad Platform developer preview.

This module intentionally has no network client.  A release is made from a
small allow-list of files in this checkout and from a validated lockfile. The
PhiCad native application and Circuit Engine are external prerequisites; they
are never copied into a Platform release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as host_platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
LOCKFILE_NAME = "versions.lock.json"
MANIFEST_NAME = "install-manifest.json"
RELEASE_FILES = ("installer.py", "platform_server.py", LOCKFILE_NAME, "release.json")
CORE_PAYLOAD_PREFIX = Path("python") / "phicad_platform"
LAUNCHER_NAMES = ("phicad-platform", "phicad-platform-mcp", "phicad-doctor", "phicad-update")
SECRET_PARTS = {
    ".env",
    ".envrc",
    "credentials",
    "credential",
    "secrets",
    "secret",
    "token",
    "tokens",
    "private-key",
    "private_key",
    "apikey",
    "api-key",
    "api_key",
    "auth",
    "oauth",
    "access_token",
    "refresh_token",
    "session",
    "identity",
    "key",
}
SECRET_DIRS = {".claude", ".codex", ".openai", ".anthropic", ".model"}
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]*$")
FLOATING_VERSION_RE = re.compile(r"^(?:latest|main|master|develop|development|trunk|head|nightly|next)$", re.I)
DEFAULT_PREREQUISITES: dict[str, dict[str, Any]] = {
    "python": {
        "label": "Python",
        "commands": ["python3", "python"],
        "minimum": "3.9",
        "required": True,
    },
    "node": {
        "label": "Node.js",
        "commands": ["node"],
        "minimum": "18",
        "required": False,
    },
    "bun": {
        "label": "Bun",
        "commands": ["bun"],
        "minimum": "1.0",
        "required": False,
    },
    "phicad": {
        "label": "PhiCad Studio + Verify",
        "commands": ["phicad", "PhiCad"],
        "minimum": None,
        "required": False,
        "path_env": "PHICAD_BIN",
    },
}
NUMBER_RE = re.compile(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class InstallerError(RuntimeError):
    """An expected, user-actionable installer failure."""


class Printer:
    def __init__(self, dry_run: bool = False, verbose: bool = False) -> None:
        self.dry_run = dry_run
        self.verbose = verbose

    def info(self, message: str) -> None:
        print(message)

    def action(self, message: str) -> None:
        print(("DRY-RUN: " if self.dry_run else "") + message)

    def debug(self, message: str) -> None:
        if self.verbose:
            print(f"  {message}")

    def warn(self, message: str) -> None:
        print(f"WARNING: {message}", file=sys.stderr)


def _path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expanduser(os.fspath(value))).absolute()


def _default_prefix() -> Path:
    return _path(os.environ.get("PHICAD_PREFIX", "~/.local/share/phicad-platform"))


def _default_bin_dir() -> Path:
    return _path(os.environ.get("PHICAD_BIN_DIR", "~/.local/bin"))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _assert_user_path(path: Path, label: str) -> None:
    """Reject paths where a typo would normally require sudo or damage macOS."""
    resolved = path.resolve(strict=False)
    forbidden = {
        Path("/"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/etc"),
        Path("/System"),
        Path("/Library"),
        Path("/Applications"),
        Path("/opt"),
        Path("/var"),
    }
    if resolved in forbidden or any(resolved.is_relative_to(item) for item in forbidden if item != Path("/")):
        raise InstallerError(f"{label} is a protected system path: {path}; installer never uses sudo")
    home = Path.home().resolve()
    # A custom prefix is useful in a temporary directory, but an absolute path
    # outside the user's writable area must already exist and be writable.  We
    # do not create a parent there as a way around normal macOS permissions.
    if not _is_relative_to(resolved, home) and not _is_relative_to(resolved, Path(tempfile.gettempdir()).resolve()):
        parent = resolved if not resolved.exists() else resolved.parent
        if not os.access(parent, os.W_OK):
            raise InstallerError(f"{label} is not writable without elevated privileges: {path}")


def _assert_no_secret_path(path: Path) -> None:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if parts & SECRET_DIRS or name in SECRET_PARTS:
        raise InstallerError(f"refusing to use a credential-looking path: {path}")


def _is_pinned_version(value: Any) -> bool:
    return isinstance(value, str) and bool(VERSION_RE.fullmatch(value)) and not FLOATING_VERSION_RE.fullmatch(value)


def _assert_safe_json(value: Any, location: str = "lockfile") -> None:
    """Do not persist a lockfile that attempts to carry a credential."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {"token", "tokens", "password", "secret", "secrets", "credential", "credentials", "privatekey", "apikey", "accesstoken", "refreshtoken", "auth", "oauth"}:
                raise InstallerError(f"{location} contains a credential field ({key!r}); credentials are never installed")
            _assert_safe_json(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_safe_json(child, f"{location}[{index}]")
    elif isinstance(value, str):
        if re.search(r"(?i)://[^/\s:@]+:[^/\s@]+@", value) or re.search(r"(?i)(token|secret|password|api[_-]?key)=", value):
            raise InstallerError(f"{location} looks like it contains a credential; credentials are never installed")


def _no_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_no_duplicate_json_keys)
    except FileNotFoundError as exc:
        raise InstallerError(f"{label} not found: {path}") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise InstallerError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InstallerError(f"{label} must contain a JSON object: {path}")
    return value


def _find_lockfile(explicit: str | None = None, source_dir: Path | None = None) -> Path:
    if explicit:
        candidate = _path(explicit)
    else:
        # A checkout-root lock is authoritative.  A copied release or an
        # explicitly supplied source uses the lock next to that source instead.
        if source_dir is SCRIPT_DIR or source_dir == SCRIPT_DIR:
            candidates = [REPO_ROOT / LOCKFILE_NAME, source_dir / LOCKFILE_NAME]
        else:
            candidates = [source_dir / LOCKFILE_NAME] if source_dir else [REPO_ROOT / LOCKFILE_NAME, SCRIPT_DIR / LOCKFILE_NAME]
        candidate = next((item for item in candidates if item.exists()), candidates[0])
    if not candidate.is_file() or candidate.is_symlink():
        raise InstallerError(f"lockfile must be a regular file: {candidate}")
    _assert_no_secret_path(candidate)
    return candidate


def _validate_lock(lock: dict[str, Any], lock_path: Path) -> str:
    # The repository's release tooling also accepts the older top-level
    # lock_schema_version/tools shape.  Read it without rewriting it: the
    # installer still copies only this lockfile and never copies the tools.
    if (lock.get("lock_schema_version") == 1 or lock.get("schema_version") == 1) and isinstance(lock.get("tools"), dict):
        tools = lock["tools"]
        native_roles = ("phicad",) if "phicad" in tools else ("phicad-studio", "phicad-verify")
        for name in native_roles:
            item = tools.get(name)
            if not isinstance(item, dict) or not isinstance(item.get("version"), str):
                raise InstallerError(f"legacy lockfile must pin {name}")
            if not _is_pinned_version(item["version"]):
                raise InstallerError(f"invalid pinned version for {name} in {lock_path}")
        native = tools[native_roles[0]]
        for name in ("phicad", "phicad-studio", "phicad-verify"):
            if name not in tools:
                continue
            for field in ("version", "source", "commit"):
                if not isinstance(tools[name], dict) or tools[name].get(field) != native.get(field):
                    raise InstallerError(f"PhiCad modes must share one native authority ({field})")
        _assert_safe_json(lock)
        version = str(lock.get("platform_version") or lock.get("harness", {}).get("version") or "0.1.0-dev.1")
        if not _is_pinned_version(version):
            raise InstallerError(f"invalid platform version in {lock_path}")
        return version

    if lock.get("schema_version") == 1 and isinstance(lock.get("components"), list):
        components = lock["components"]
        found: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(components):
            if not isinstance(item, dict):
                raise InstallerError(f"components[{index}] in {lock_path} must be an object")
            name = str(item.get("name", "")).strip().lower()
            if name in {"phicad", "phicad-verify", "phicad-studio"}:
                if name not in found:
                    found[name] = item
                else:
                    raise InstallerError(f"duplicate component {name} in {lock_path}")
                version = item.get("version")
                pin = item.get("pin")
                if not _is_pinned_version(version):
                    raise InstallerError(f"{name} is not pinned to an exact version in {lock_path}")
                if not isinstance(pin, str) or not pin.strip() or pin.lstrip().startswith(("^", "~", ">", "<", "=")) or re.search(r"(^|[-_/])(main|master|latest|head|nightly)($|[-_/])", pin, re.I):
                    raise InstallerError(f"{name} is not pinned to an immutable ref in {lock_path}")
                if item.get("vendored", False) or item.get("bundled", False):
                    raise InstallerError(f"{name} must remain a separate component")
        if not ({"phicad", "phicad-verify", "phicad-studio"} & found.keys()):
            raise InstallerError(f"lockfile must pin the PhiCad native component: {lock_path}")
        _assert_safe_json(lock)
        version = str(lock.get("platform_version") or lock.get("harness", {}).get("version") or "0.1.0-dev.1")
        if not _is_pinned_version(version):
            raise InstallerError(f"invalid platform version in {lock_path}")
        return version

    if lock.get("schema_version") != 1:
        raise InstallerError(f"unsupported lockfile schema in {lock_path}; expected schema_version 1")
    platform_info = lock.get("platform")
    if not isinstance(platform_info, dict):
        raise InstallerError(f"{lock_path} is missing platform metadata")
    version = platform_info.get("version")
    if not _is_pinned_version(version):
        raise InstallerError(f"invalid platform version in {lock_path}")
    prerequisites = lock.get("prerequisites")
    if not isinstance(prerequisites, dict):
        raise InstallerError(f"{lock_path} is missing prerequisites")
    for key, item in prerequisites.items():
        if not isinstance(item, dict) or not isinstance(item.get("commands"), list):
            raise InstallerError(f"invalid prerequisite entry {key!r} in {lock_path}")
        if not all(isinstance(command, str) and command for command in item["commands"]):
            raise InstallerError(f"invalid prerequisite commands for {key!r} in {lock_path}")
    components = lock.get("components")
    if not isinstance(components, dict):
        raise InstallerError(f"{lock_path} is missing components")
    for name in ("phicad",):
        item = components.get(name)
        if not isinstance(item, dict):
            raise InstallerError(f"lockfile must pin the {name} native component")
        if item.get("kind") not in {"checkout", "binary"}:
            raise InstallerError(f"{name} must be a checkout or binary in {lock_path}")
        component_version = item.get("version")
        if not _is_pinned_version(component_version):
            raise InstallerError(f"{name} is not pinned to a version in {lock_path}")
        if item.get("bundled", False):
            raise InstallerError(f"{name} must remain separate; it cannot be bundled by the installer")
    _assert_safe_json(lock)
    return version


def _normalize_lock(lock: dict[str, Any]) -> dict[str, Any]:
    """Return the installer view while leaving the source lock untouched."""
    if (
        lock.get("schema_version") == 1
        and isinstance(lock.get("platform"), dict)
        and isinstance(lock.get("prerequisites"), dict)
        and isinstance(lock.get("components"), dict)
    ):
        return lock
    if lock.get("schema_version") == 1 and isinstance(lock.get("components"), list):
        components = {str(item.get("name", "")).strip().lower(): item for item in lock["components"] if isinstance(item, dict)}
        phicad = components.get("phicad") or components.get("phicad-verify") or components.get("phicad-studio") or {}
        return {
            "schema_version": 1,
            "platform": {"name": "phicad-platform", "version": str(lock.get("platform_version") or lock.get("harness", {}).get("version") or "0.1.0-dev.1"), "channel": "developer-preview"},
            "prerequisites": json.loads(json.dumps(DEFAULT_PREREQUISITES)),
            "components": {
                "phicad": {"kind": "binary", "version": str(phicad.get("version")), "path_env": "PHICAD_BIN", "bundled": False},
            },
            "source_lock_schema": "schema_version/components[]",
        }
    tools = lock.get("tools", {})
    phicad_item = tools.get("phicad") or tools.get("phicad-verify") or tools.get("phicad-studio") or {}
    phicad_version = str(phicad_item.get("version", "0.1.0-dev.1"))
    return {
        "schema_version": 1,
        "platform": {"name": "phicad-platform", "version": str(lock.get("platform_version") or lock.get("harness", {}).get("version") or "0.1.0-dev.1"), "channel": "developer-preview"},
        "prerequisites": json.loads(json.dumps(DEFAULT_PREREQUISITES)),
        "components": {
            "phicad": {"kind": "binary", "version": phicad_version, "path_env": "PHICAD_BIN", "bundled": False},
        },
        "source_lock_schema": "lock_schema_version/tools",
    }


def _read_lock(path: Path) -> tuple[dict[str, Any], str]:
    lock = _load_json(path, "lockfile")
    version = _validate_lock(lock, path)
    return _normalize_lock(lock), version


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_tuple(value: str) -> tuple[int, int, int, int, int]:
    match = re.search(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]([A-Za-z]+)[.-]?(\d+)?)?", value)
    if not match:
        return (0, 0, 0, 0, 0)
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    # Stable releases sort after a prerelease.  Build metadata (including a
    # lock digest) is intentionally ignored here.
    stable = 1 if not match.group(4) else 0
    prerelease_number = int(match.group(5) or 0)
    return (major, minor, patch, stable, prerelease_number)


def _probe_command(command: str) -> tuple[bool, str]:
    found = shutil.which(command)
    if not found:
        return False, "not found"
    try:
        result = subprocess.run(
            [found, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return True, f"{found} (unreadable: {exc})"
    output = (result.stdout or "").strip().splitlines()
    detail = output[0][:160] if output else found
    return True, f"{found} ({detail})"


def _probe_path_override(value: str) -> tuple[bool, str]:
    candidate = _path(value)
    if not candidate.exists():
        return False, f"missing path {candidate}"
    if candidate.is_symlink():
        return False, f"refusing symlink prerequisite {candidate}"
    if candidate.is_dir():
        return True, str(candidate)
    if not os.access(candidate, os.X_OK):
        return False, f"not executable {candidate}"
    return True, str(candidate)


def _probe_known_app(key: str) -> tuple[bool, str]:
    names = {"phicad": ("PhiCad.app", "phicad.app")}.get(key, ())
    roots = (Path.home() / "Applications", Path("/Applications"))
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_dir() and not candidate.is_symlink():
                return True, str(candidate)
    return False, "not found"


def check_prerequisites(lock: dict[str, Any], printer: Printer, allow_non_macos: bool = False) -> bool:
    printer.info("PhiCad Platform developer-preview prerequisite check")
    if host_platform.system() != "Darwin":
        message = f"host is {host_platform.system()}, while this preview targets macOS"
        if allow_non_macos:
            printer.warn(message + " (continuing because non-macOS checks were explicitly allowed)")
        else:
            printer.warn(message + "; results are advisory")

    all_required_ok = True
    prerequisites = lock.get("prerequisites", {})
    for key, item in prerequisites.items():
        label = str(item.get("label", key))
        override_name = item.get("path_env")
        if override_name and os.environ.get(override_name):
            ok, detail = _probe_path_override(os.environ[override_name])
        else:
            ok, detail = False, "not found"
            for command in item.get("commands", []):
                ok, detail = _probe_command(command)
                if ok:
                    break
            if not ok and key == "phicad":
                ok, detail = _probe_known_app(key)
        minimum = item.get("minimum")
        suffix = f"; requires >= {minimum}" if minimum else ""
        if ok and minimum:
            version_text = detail.split("(", 1)[1] if "(" in detail else detail
            found_version = NUMBER_RE.search(version_text)
            required_version = NUMBER_RE.search(str(minimum))
            if found_version and required_version:
                found = tuple(int(part or 0) for part in found_version.groups())
                required = tuple(int(part or 0) for part in required_version.groups())
                if found < required:
                    ok = False
                    detail += f" (too old; found {found[0]}.{found[1]}.{found[2]})"
        if ok:
            printer.info(f"  [ok]   {label}: {detail}{suffix}")
        else:
            required = bool(item.get("required", False))
            printer.info(f"  [{'FAIL' if required else 'warn'}] {label}: {detail}{suffix}")
            if required:
                all_required_ok = False

    for name, item in lock.get("components", {}).items():
        env_name = item.get("path_env")
        configured = os.environ.get(env_name, "") if env_name else ""
        if configured:
            ok, detail = _probe_path_override(configured)
            state = "ok" if ok else "warn"
            printer.info(f"  [{state}]   separate {name} {item.get('version')}: {detail}")
        else:
            printer.info(
                f"  [info] separate {name} is pinned at {item.get('version')} but not bundled "
                f"(set {env_name or 'its path'} to check it)"
            )
    printer.info("  [info] no network downloads are performed; PhiCad and the Circuit Engine stay separate")
    return all_required_ok


def _source_dir(value: str | None) -> Path:
    if value:
        source = _path(value)
    elif (SCRIPT_DIR / LOCKFILE_NAME).is_file() and (SCRIPT_DIR / "platform_server.py").is_file():
        # This also works after the installer is copied into a versioned
        # release: an installed updater can safely repeat the current release.
        source = SCRIPT_DIR
    else:
        source = REPO_ROOT
    if (source / "scripts" / "install").is_dir():
        source = source / "scripts" / "install"
    if not source.is_dir():
        raise InstallerError(f"source directory does not contain scripts/install: {source}")
    return source


def _payload_sources(source: Path, lock_path: Path) -> dict[Path, Path]:
    """Return the only checkout files allowed into a versioned release."""
    payload: dict[Path, Path] = {
        Path("installer.py"): source / "installer.py",
        Path("platform_server.py"): source / "platform_server.py",
        Path(LOCKFILE_NAME): lock_path,
    }
    # The package is optional in a minimal installer checkout.  When present,
    # install only Python source below this one known package root; never walk
    # the repository or copy a virtualenv, home directory, or build artifact.
    repo_root = source.parent.parent
    package_root = repo_root / "src" / "phicad_platform"
    if package_root.is_dir() and not package_root.is_symlink():
        for candidate in sorted(package_root.rglob("*.py")):
            if candidate.is_file() and not candidate.is_symlink():
                relative = CORE_PAYLOAD_PREFIX / candidate.relative_to(package_root)
                _assert_no_secret_path(candidate)
                payload[relative] = candidate
    # Cross-view handoffs open the installed, version-matched local docs.  Copy
    # only known documentation/media extensions; never walk arbitrary payloads.
    docs_root = repo_root / "docs"
    allowed_doc_suffixes = {".md", ".html", ".png", ".svg", ".pdf", ".json"}
    if docs_root.is_dir() and not docs_root.is_symlink():
        for candidate in sorted(docs_root.rglob("*")):
            if candidate.is_file() and not candidate.is_symlink() and candidate.suffix.lower() in allowed_doc_suffixes:
                _assert_no_secret_path(candidate)
                payload[Path("docs") / candidate.relative_to(docs_root)] = candidate
    for name in ("README.md", "THIRD_PARTY_NOTICES.md"):
        candidate = repo_root / name
        if candidate.is_file() and not candidate.is_symlink():
            payload[Path(name)] = candidate
    licenses_root = repo_root / "LICENSES"
    if licenses_root.is_dir() and not licenses_root.is_symlink():
        for candidate in sorted(licenses_root.rglob("*")):
            if candidate.is_file() and not candidate.is_symlink():
                payload[Path("LICENSES") / candidate.relative_to(licenses_root)] = candidate
    return payload


def _release_file_names(release: Path) -> list[Path]:
    return sorted(
        path.relative_to(release)
        for path in release.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _copy_regular(source: Path, destination: Path, mode: int = 0o644) -> None:
    if not source.is_file() or source.is_symlink():
        raise InstallerError(f"refusing to install non-regular payload: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle)
    os.chmod(destination, mode)


def _atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink():
        raise InstallerError(f"manifest must not be a symlink: {path}")
    manifest = _load_json(path, "install manifest")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise InstallerError(f"unsupported or corrupt install manifest: {path}")
    return manifest


def _file_set(manifest: dict[str, Any] | None) -> set[Path]:
    if not manifest:
        return set()
    result: set[Path] = set()
    for item in manifest.get("files", []):
        if not isinstance(item, str):
            raise InstallerError("install manifest contains a non-path entry")
        result.add(_path(item))
    return result


def _launcher_text(prefix: Path, bin_dir: Path, kind: str, use_package: bool) -> str:
    quoted_prefix = _shell_quote(str(prefix))
    quoted_bin_dir = _shell_quote(str(bin_dir))
    if kind in {"platform", "mcp"}:
        if use_package:
            module = "phicad_platform.cli" if kind == "platform" else "phicad_platform.mcp_server"
            return textwrap.dedent(
                f"""\
                #!/bin/sh
                # PhiCad Platform developer-preview launcher; generated by install.sh.
                set -eu
                PHICAD_PLATFORM_PREFIX={quoted_prefix}
                exec /usr/bin/env PYTHONPATH="$PHICAD_PLATFORM_PREFIX/current/python" python3 -m {module} "$@"
                """
            )
        if kind == "platform":
            return textwrap.dedent(
                f"""\
                #!/bin/sh
                set -eu
                PHICAD_PLATFORM_PREFIX={quoted_prefix}
                case "${{1-}}" in
                    --version) exec /usr/bin/env python3 "$PHICAD_PLATFORM_PREFIX/current/platform_server.py" --version ;;
                    *) echo "ERROR: this minimal release exposes MCP only; install the full platform package" >&2; exit 2 ;;
                esac
                """
            )
        target = "$PHICAD_PLATFORM_PREFIX/current/platform_server.py"
        return textwrap.dedent(
            f"""\
            #!/bin/sh
            # PhiCad Platform developer-preview MCP launcher; generated by install.sh.
            set -eu
            PHICAD_PLATFORM_PREFIX={quoted_prefix}
            exec /usr/bin/env python3 "{target}" "$@"
            """
        )
    command = " doctor" if kind == "doctor" else " update"
    return textwrap.dedent(
        f"""\
        #!/bin/sh
        # PhiCad Platform developer-preview launcher; generated by install.sh.
        set -eu
        PHICAD_PLATFORM_PREFIX={quoted_prefix}
        exec /usr/bin/env python3 "$PHICAD_PLATFORM_PREFIX/current/installer.py"{command} --prefix "$PHICAD_PLATFORM_PREFIX" --bin-dir {quoted_bin_dir} "$@"
        """
    )


def _shell_quote(value: str) -> str:
    # Avoid importing shell utilities and keep generated launchers portable.
    return "'" + value.replace("'", "'\\''") + "'"


def _launcher_snapshot(path: Path) -> tuple[bool, bytes | None, int | None]:
    if not path.exists() and not path.is_symlink():
        return False, None, None
    if path.is_symlink() or not path.is_file():
        raise InstallerError(f"refusing to replace non-regular launcher: {path}")
    return True, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def _ensure_launcher(path: Path, content: str, owned_files: set[Path], printer: Printer) -> None:
    if path.exists() or path.is_symlink():
        if path not in owned_files:
            raise InstallerError(f"launcher already exists and is not owned by this installer: {path}")
        old_mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else 0o755
    else:
        old_mode = 0o755
    printer.action(f"install launcher {path}")
    if not printer.dry_run:
        _atomic_write(path, content.encode("utf-8"), 0o755)
    elif old_mode != 0o755:
        printer.debug(f"would normalize launcher mode from {oct(old_mode)}")


def _current_target(prefix: Path) -> str | None:
    current = prefix / "current"
    if not current.is_symlink():
        return None
    return os.readlink(current)


def _installed_lock_sha(prefix: Path) -> str | None:
    metadata = prefix / "current" / "release.json"
    if not metadata.is_file() or metadata.is_symlink():
        return None
    try:
        value = _load_json(metadata, "release metadata").get("lock_sha256")
    except InstallerError:
        return None
    return value if isinstance(value, str) else None


def _switch_current(prefix: Path, version: str, printer: Printer) -> None:
    current = prefix / "current"
    if current.exists() and not current.is_symlink():
        raise InstallerError(f"refusing to replace non-symlink current pointer: {current}")
    temporary = prefix / f".current.{os.getpid()}.{time.time_ns()}"
    printer.action(f"point {current} at releases/{version}")
    if printer.dry_run:
        return
    os.symlink(str(Path("releases") / version), temporary)
    os.replace(temporary, current)


def _restore_current(prefix: Path, old_target: str | None) -> None:
    current = prefix / "current"
    try:
        if current.exists() or current.is_symlink():
            current.unlink()
        if old_target is not None:
            temporary = prefix / f".restore-current.{os.getpid()}.{time.time_ns()}"
            os.symlink(old_target, temporary)
            os.replace(temporary, current)
    except OSError:
        # The original exception is more useful than a best-effort rollback
        # failure.  The old release itself is never removed during rollback.
        pass


def _write_release(source: Path, lock_path: Path, lock: dict[str, Any], version: str, prefix: Path, printer: Printer) -> Path:
    releases = prefix / "releases"
    destination = releases / version
    if destination.exists():
        if not destination.is_dir() or destination.is_symlink():
            raise InstallerError(f"release path is not a directory: {destination}")
        # A release is immutable.  Reusing a complete matching release is safe;
        # silently replacing a hand-edited release is not.
        for name in RELEASE_FILES[:-1]:
            if not (destination / name).is_file():
                raise InstallerError(f"existing release is incomplete: {destination}")
        existing_lock, existing_version = _read_lock(destination / LOCKFILE_NAME)
        if existing_version != version or _sha256(destination / LOCKFILE_NAME) != _sha256(lock_path):
            raise InstallerError(f"release already exists with different contents: {destination}")
        printer.info(f"using existing immutable release {destination}")
        return destination

    stage = prefix / ".staging" / f"{version}.{os.getpid()}.{time.time_ns()}"
    printer.action(f"stage platform release {version} at {stage}")
    if printer.dry_run:
        return destination
    stage.mkdir(parents=True, exist_ok=False)
    try:
        payload = _payload_sources(source, lock_path)
        for relative, payload_source in payload.items():
            _copy_regular(payload_source, stage / relative)
        release_metadata = {
            "schema_version": 1,
            "name": "phicad-platform",
            "version": version,
            "channel": lock.get("platform", {}).get("channel", "developer-preview"),
            "lock_sha256": _sha256(lock_path),
            "payload": [str(item) for item in sorted(payload)],
        }
        _atomic_write(
            stage / "release.json",
            (json.dumps(release_metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            0o644,
        )
        releases.mkdir(parents=True, exist_ok=True)
        os.replace(stage, destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return destination


def _manifest_payload(prefix: Path, bin_dir: Path, release: Path, version: str, old: dict[str, Any] | None) -> dict[str, Any]:
    files = _file_set(old)
    files.update(release / name for name in _release_file_names(release))
    files.update(bin_dir / name for name in LAUNCHER_NAMES)
    files.add(prefix / "current")
    files.add(prefix / MANIFEST_NAME)
    hashes: dict[str, str] = {}
    for item in files:
        # current is an intentional symlink and cannot be content-hashed as a
        # regular file.  Hashes let uninstall preserve a user-modified file.
        if item.name != "current" and item.is_file() and not item.is_symlink():
            hashes[str(item)] = _sha256(item)
    return {
        "schema_version": 1,
        "product": "phicad-platform",
        "channel": "developer-preview",
        "prefix": str(prefix),
        "bin_dir": str(bin_dir),
        "current_version": version,
        "files": sorted(str(item) for item in files),
        "hashes": hashes,
        "created_at": int(time.time()),
        "limitations": [
            "developer preview for macOS",
            "PhiCad and the Circuit Engine are separate pinned prerequisites",
            "no credentials or secrets are installed by this manifest",
        ],
    }


def _restore_snapshots(snapshots: dict[Path, tuple[bool, bytes | None, int | None]]) -> None:
    for path, (existed, content, mode) in snapshots.items():
        try:
            if existed and content is not None:
                _atomic_write(path, content, mode or 0o755)
            elif path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass


def _config_candidates() -> list[Path]:
    home = Path.home()
    xdg = _path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
    return [
        _path(os.environ["PHI_CONFIG"]) if os.environ.get("PHI_CONFIG") else None,
        _path(os.environ["PHI_CONFIG_PATH"]) if os.environ.get("PHI_CONFIG_PATH") else None,
        home / ".pi" / "agent" / "mcp.json",
        xdg / "phi" / "config.json",
        xdg / "phi" / "settings.json",
        home / ".phi" / "config.json",
        home / ".phi" / "settings.json",
    ]


def _choose_config(explicit: str | None) -> Path:
    if explicit:
        candidate = _path(explicit)
    else:
        candidates = [item for item in _config_candidates() if item is not None]
        existing = next((item for item in candidates if item.exists()), None)
        candidate = existing or candidates[0]
    _assert_no_secret_path(candidate)
    return candidate


def _backup_config(path: Path, printer: Printer) -> Path | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise InstallerError(f"Phi config must be a regular file before an opt-in edit: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    for index in range(1000):
        suffix = f".phicad-platform.bak-{int(time.time())}" + (f"-{index}" if index else "")
        backup = Path(str(path) + suffix)
        if not backup.exists():
            printer.action(f"back up Phi config to {backup}")
            if not printer.dry_run:
                with path.open("rb") as source, backup.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
                os.chmod(backup, mode)
            return backup
    raise InstallerError(f"could not choose a non-destructive backup name for {path}")


def _mcp_container(config: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    if "mcpServers" in config:
        container = config["mcpServers"]
        if not isinstance(container, dict):
            raise InstallerError("Phi config mcpServers must be an object; refusing to clobber it")
        return container, "mcpServers"
    if "mcp_servers" in config:
        container = config["mcp_servers"]
        if not isinstance(container, dict):
            raise InstallerError("Phi config mcp_servers must be an object; refusing to clobber it")
        return container, "mcp_servers"
    mcp = config.get("mcp")
    if isinstance(mcp, dict) and "servers" in mcp:
        container = mcp["servers"]
        if not isinstance(container, dict):
            raise InstallerError("Phi config mcp.servers must be an object; refusing to clobber it")
        return container, "mcp.servers"
    if mcp is not None and not isinstance(mcp, dict):
        raise InstallerError("Phi config mcp must be an object; refusing to clobber it")
    config["mcpServers"] = {}
    return config["mcpServers"], "mcpServers"


def register_phi(config_path: Path, launcher: Path, printer: Printer) -> None:
    _assert_no_secret_path(config_path)
    if config_path.exists():
        if config_path.is_symlink() or not config_path.is_file():
            raise InstallerError(f"refusing to edit non-regular Phi config: {config_path}")
        config = _load_json(config_path, "Phi config")
        mode = stat.S_IMODE(config_path.stat().st_mode)
    else:
        config = {}
        mode = 0o600
    backup = _backup_config(config_path, printer)
    container, location = _mcp_container(config)
    # This is the complete entry by design: no env, token, working directory,
    # or inherited credential source is sent to the stdio process.
    container["phicad-platform"] = {
        "command": str(launcher),
        "args": [],
    }
    printer.action(f"register credential-free phicad-platform in {config_path} ({location})")
    if printer.dry_run:
        return
    data = (json.dumps(config, indent=2, sort_keys=False) + "\n").encode("utf-8")
    try:
        _atomic_write(config_path, data, mode)
    except BaseException:
        if backup and backup.exists():
            try:
                shutil.copy2(backup, config_path)
                os.chmod(config_path, mode)
            except OSError:
                pass
        raise


def _install_or_update(args: argparse.Namespace, operation: str) -> int:
    printer = Printer(args.dry_run, args.verbose)
    prefix = _path(args.prefix) if args.prefix else _default_prefix()
    bin_dir = _path(args.bin_dir) if args.bin_dir else _default_bin_dir()
    _assert_user_path(prefix, "prefix")
    _assert_user_path(bin_dir, "bin directory")
    if prefix.is_symlink() or bin_dir.is_symlink():
        raise InstallerError("prefix and bin directory must not themselves be symlinks")
    if prefix == bin_dir or _is_relative_to(bin_dir, prefix):
        # A bin directory inside the release tree would make rollback and
        # uninstall ambiguous.  A sibling prefix/bin is fine when explicitly
        # requested, but the default remains ~/.local/bin.
        if bin_dir == prefix:
            raise InstallerError("bin directory must not be the versioned prefix itself")

    source = _source_dir(args.source)
    lock_path = _find_lockfile(args.lockfile, source)
    lock, version = _read_lock(lock_path)
    if not check_prerequisites(lock, printer, args.allow_non_macos):
        raise InstallerError("required prerequisites are missing; use --check for details")
    if operation == "update":
        old_manifest = _load_manifest(prefix / MANIFEST_NAME)
        if not old_manifest:
            raise InstallerError(f"cannot update without an install manifest: {prefix / MANIFEST_NAME}")
        old_version = str(old_manifest.get("current_version", ""))
        if old_version and _version_tuple(version) < _version_tuple(old_version):
            raise InstallerError(f"refusing rollback from {old_version} to older lockfile {version}; install it explicitly if intended")
        source_lock_sha = _sha256(lock_path)
        installed_lock_sha = _installed_lock_sha(prefix)
        if _version_tuple(version) == _version_tuple(old_version):
            if installed_lock_sha == source_lock_sha:
                printer.info(f"already at lockfile version {old_version}; no update needed")
                return 0
            # A dependency-only lock change is still a new immutable release.
            # Build metadata keeps the human platform version while ensuring
            # the versioned directory can never be overwritten in place.
            version = f"{version}+lock.{source_lock_sha[:12]}"
    else:
        old_manifest = _load_manifest(prefix / MANIFEST_NAME) if (prefix / MANIFEST_NAME).exists() else None

    printer.info("Developer-preview limitations: macOS target; no automatic dependency downloads; separate PhiCad/Circuit Engine prerequisites; preview APIs may change.")
    if args.dry_run:
        printer.action(f"create versioned prefix {prefix}")
    else:
        prefix.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)

    old_current = _current_target(prefix)
    release_existed = (prefix / "releases" / version).exists()
    release = _write_release(source, lock_path, lock, version, prefix, printer)
    use_package = (release / CORE_PAYLOAD_PREFIX / "mcp_server.py").is_file()
    launcher_paths = {
        "platform": bin_dir / "phicad-platform",
        "mcp": bin_dir / "phicad-platform-mcp",
        "doctor": bin_dir / "phicad-doctor",
        "update": bin_dir / "phicad-update",
    }
    if old_manifest:
        _safe_manifest_paths(old_manifest, prefix)
    owned = _file_set(old_manifest)
    snapshots: dict[Path, tuple[bool, bytes | None, int | None]] = {}
    switched = False
    try:
        for kind, path in launcher_paths.items():
            if not args.dry_run:
                snapshots[path] = _launcher_snapshot(path)
            _ensure_launcher(path, _launcher_text(prefix, bin_dir, kind, use_package), owned, printer)
        _switch_current(prefix, version, printer)
        switched = not args.dry_run
        manifest = _manifest_payload(prefix, bin_dir, release, version, old_manifest)
        printer.action(f"write install manifest {prefix / MANIFEST_NAME}")
        if not args.dry_run:
            _atomic_write(
                prefix / MANIFEST_NAME,
                (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                0o644,
            )
    except BaseException:
        if not args.dry_run:
            _restore_snapshots(snapshots)
            if switched:
                _restore_current(prefix, old_current)
            # A newly staged release is safe to remove only when it was not the
            # old immutable release.  The old release is deliberately retained.
            if not release_existed and release.name == version and old_current != str(Path("releases") / version):
                # Do not recursively remove an existing release.  Only the
                # payload just created by this transaction is cleaned up.
                for item in _release_file_names(release):
                    try:
                        (release / item).unlink()
                    except FileNotFoundError:
                        pass
                for directory in sorted(
                    (item for item in release.rglob("*") if item.is_dir() and not item.is_symlink()),
                    key=lambda item: len(item.parts),
                    reverse=True,
                ):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                try:
                    release.rmdir()
                except OSError:
                    pass
        raise

    if args.yes and not args.no_config:
        config_path = _choose_config(args.phi_config)
        register_phi(config_path, launcher_paths["mcp"], printer)
    else:
        printer.info("Phi config unchanged (use --yes to opt in to MCP registration, or --no-config to keep it disabled).")
    printer.info(f"installed phicad-platform {version} at {prefix / 'releases' / version}")
    printer.info(
        f"launchers: {bin_dir / 'phicad-platform'}, {bin_dir / 'phicad-platform-mcp'}, "
        f"{bin_dir / 'phicad-doctor'}, {bin_dir / 'phicad-update'}"
    )
    return 0


def _safe_manifest_paths(manifest: dict[str, Any], prefix: Path) -> list[Path]:
    if manifest.get("product") != "phicad-platform":
        raise InstallerError("manifest product does not match phicad-platform")
    recorded_prefix = manifest.get("prefix")
    if not isinstance(recorded_prefix, str) or _path(recorded_prefix) != prefix:
        raise InstallerError("manifest prefix does not match the requested uninstall prefix")
    bin_dir = _path(str(manifest.get("bin_dir", _default_bin_dir())))
    _assert_user_path(bin_dir, "manifest bin directory")
    if prefix.is_symlink() or bin_dir.is_symlink():
        raise InstallerError("refusing a manifest rooted at a symlink directory")
    paths: list[Path] = []
    for raw in manifest.get("files", []):
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise InstallerError("manifest paths must be absolute")
        path = _path(raw)
        in_prefix = _is_relative_to(path, prefix)
        in_bin = _is_relative_to(path, bin_dir)
        if not in_prefix and not in_bin:
            raise InstallerError(f"manifest contains path outside its prefix/bin roots: {path}")
        if path in {prefix, bin_dir}:
            raise InstallerError(f"manifest may not remove an installation root: {path}")
        if in_bin and not in_prefix and (path.parent != bin_dir or path.name not in set(LAUNCHER_NAMES)):
            raise InstallerError(f"manifest contains an unexpected external file: {path}")
        paths.append(path)
    return paths


def uninstall(args: argparse.Namespace) -> int:
    printer = Printer(args.dry_run, args.verbose)
    prefix = _path(args.prefix) if args.prefix else _default_prefix()
    _assert_user_path(prefix, "prefix")
    manifest_path = prefix / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    if not manifest:
        printer.info(f"nothing installed at {prefix} (manifest absent)")
        return 0
    paths = _safe_manifest_paths(manifest, prefix)
    if not args.yes and not args.dry_run:
        if not sys.stdin.isatty():
            raise InstallerError("uninstall is non-interactive; pass --yes to confirm")
        answer = input(f"Remove only {len(paths)} manifest-listed files from {prefix}? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            printer.info("uninstall cancelled")
            return 0
    printer.info("Uninstall removes only paths listed in the install manifest; Phi config and backups are never removed.")
    manifest_hashes = manifest.get("hashes", {})
    skipped = 0
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        if path == manifest_path:
            continue
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_dir() and not path.is_symlink():
            printer.warn(f"leaving unexpected directory (never recursive): {path}")
            skipped += 1
            continue
        expected = manifest_hashes.get(str(path)) if isinstance(manifest_hashes, dict) else None
        if path.is_file() and not expected:
            printer.warn(f"leaving unhashed manifest-listed file: {path}")
            skipped += 1
            continue
        if expected and path.is_file() and _sha256(path) != expected:
            printer.warn(f"leaving modified manifest-listed file: {path}")
            skipped += 1
            continue
        printer.action(f"remove {path}")
        if not args.dry_run:
            path.unlink()
    printer.action(f"remove {manifest_path}")
    if not args.dry_run and manifest_path.exists():
        manifest_path.unlink()
    # Remove only empty parents that contained manifest-listed files.  No
    # directory is recursively deleted and a non-empty user directory is left
    # alone, including directories that were not made by this installer.
    if not args.dry_run:
        known_directories: set[Path] = set()
        for path in paths:
            if _is_relative_to(path, prefix):
                parent = path.parent
                while _is_relative_to(parent, prefix) and parent != prefix:
                    known_directories.add(parent)
                    parent = parent.parent
        known_directories.update({prefix / "releases", prefix / ".staging", prefix})
        for directory in sorted(known_directories, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
    if skipped:
        printer.warn(f"{skipped} modified/unexpected manifest paths were left in place")
    printer.info("uninstall complete; user configuration, backups, and separate prerequisites were not touched")
    return 0 if not skipped else 1


def doctor(args: argparse.Namespace) -> int:
    printer = Printer(args.dry_run, args.verbose)
    source = _source_dir(args.source)
    lock_path = _find_lockfile(args.lockfile, source)
    lock, _ = _read_lock(lock_path)
    ok = check_prerequisites(lock, printer, args.allow_non_macos)
    prefix = _path(args.prefix) if args.prefix else _default_prefix()
    manifest = _load_manifest(prefix / MANIFEST_NAME) if (prefix / MANIFEST_NAME).exists() else None
    if manifest:
        current = prefix / "current"
        if current.is_symlink() and (current / "installer.py").is_file():
            printer.info(f"  [ok]   installed release: {manifest.get('current_version')} at {current}")
        else:
            printer.info("  [FAIL] installed release pointer is missing or incomplete")
            ok = False
        for name in LAUNCHER_NAMES:
            launcher = _path(str(manifest.get("bin_dir", _default_bin_dir()))) / name
            if launcher.is_file() and os.access(launcher, os.X_OK):
                printer.info(f"  [ok]   launcher: {launcher}")
            else:
                printer.info(f"  [FAIL] launcher missing: {launcher}")
                ok = False
    else:
        printer.info(f"  [info] no platform install manifest at {prefix}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install, update, inspect, or uninstall the PhiCad Platform macOS developer preview.",
        epilog=(
            "No network or sudo is used. No credentials are copied or generated. "
            "Use --yes to opt in to the one Phi MCP config merge; --no-config disables it. "
            "Use --dry-run to print writes without changing the filesystem."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    def common(command: argparse.ArgumentParser, include_source: bool = True) -> None:
        command.add_argument("--prefix", help="versioned user install directory (default: ~/.local/share/phicad-platform)")
        command.add_argument("--bin-dir", help="launcher directory (default: ~/.local/bin)")
        command.add_argument("--lockfile", help="validated local versions.lock.json")
        if include_source:
            command.add_argument("--source", help="local checkout containing scripts/install (update source)")
        command.add_argument("--yes", action="store_true", help="confirm install/uninstall and opt in to Phi MCP registration")
        command.add_argument("--no-config", action="store_true", help="do not edit Phi configuration")
        command.add_argument("--phi-config", help="explicit Phi JSON config path for the opt-in merge")
        command.add_argument("--dry-run", "-n", action="store_true", help="show changes without writing")
        command.add_argument("--check", action="store_true", help="check prerequisites only; do not install or update")
        command.add_argument("--allow-non-macos", action="store_true", help="allow advisory checks on a non-macOS host")
        command.add_argument("--verbose", action="store_true")

    install_parser = subparsers.add_parser("install", help="install a versioned developer preview")
    common(install_parser)
    update_parser = subparsers.add_parser("update", help="install a newer local lockfile release transactionally")
    common(update_parser)
    doctor_parser = subparsers.add_parser("doctor", help="check prerequisites and installed files")
    common(doctor_parser)
    check_parser = subparsers.add_parser("check", help="check prerequisites without changing files")
    common(check_parser)
    uninstall_parser = subparsers.add_parser("uninstall", help="remove only manifest-listed installed files")
    common(uninstall_parser, include_source=False)
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "install"
    try:
        if command in {"install", "update"} and args.check:
            source = _source_dir(args.source)
            lock_path = _find_lockfile(args.lockfile, source)
            lock, _ = _read_lock(lock_path)
            return 0 if check_prerequisites(lock, Printer(args.dry_run, args.verbose), args.allow_non_macos) else 1
        if command == "install":
            return _install_or_update(args, "install")
        if command == "update":
            return _install_or_update(args, "update")
        if command == "check":
            source = _source_dir(args.source)
            lock_path = _find_lockfile(args.lockfile, source)
            lock, _ = _read_lock(lock_path)
            return 0 if check_prerequisites(lock, Printer(args.dry_run, args.verbose), args.allow_non_macos) else 1
        if command == "doctor":
            return doctor(args)
        if command == "uninstall":
            return uninstall(args)
        parser.error(f"unknown command {command}")
    except InstallerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ERROR: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
