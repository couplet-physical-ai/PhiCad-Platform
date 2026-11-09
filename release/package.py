#!/usr/bin/env python3
"""Build a deterministic, checksumed PhiCad Platform developer-preview archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # Support both direct execution and imports from release.tests.
    from .inventory import build_inventory
    from .secret_scan import scan_paths
    from .validate_versions import default_lock_path, load_lock
except ImportError:  # pragma: no cover - exercised by the Makefile entry point.
    from inventory import build_inventory
    from secret_scan import scan_paths
    from validate_versions import default_lock_path, load_lock


VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
ARCHIVE_NAME = "phicad-platform-%s.tar.gz"
EXTERNAL_COMPONENTS = {"phicad", "tscircuit"}
EXTERNAL_PARENT_DIRS = {
    "vendor",
    "vendors",
    "external",
    "upstream",
    "third_party",
    "third-party",
    "node_modules",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tscircuit",
    ".coverage",
    ".tox",
    "build",
    "dist",
}
LAYOUT_CONTRACT = {
    "code": "platform source and integration code",
    "docs": "documentation and usage material",
    "installers": "installer scripts and packaging helpers",
    "assets": "runtime and UI assets",
    "examples": "example projects and fixtures",
    "notices": "license and third-party notice material",
}


def _git_output(root: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def source_date_epoch(root: Path, requested: Optional[int] = None) -> int:
    if requested is not None:
        value = requested
    elif os.environ.get("SOURCE_DATE_EPOCH"):
        value = int(os.environ["SOURCE_DATE_EPOCH"])
    else:
        commit_time = _git_output(root, "show", "-s", "--format=%ct", "HEAD")
        value = int(commit_time) if commit_time and commit_time.isdigit() else 0
    if value < 0:
        raise ValueError("SOURCE_DATE_EPOCH must be non-negative")
    return value


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _path_is_external(relative: Path) -> bool:
    for index, part in enumerate(relative.parts):
        if part.lower() in EXTERNAL_COMPONENTS and (
            index == 0 or any(parent.lower() in EXTERNAL_PARENT_DIRS for parent in relative.parts[:index])
        ):
            return True
    return False


def _path_is_excluded(relative: Path, output_dir: Path, root: Path) -> bool:
    if not relative.parts or relative.parts[0] == ".git":
        return True
    if set(relative.parts) & EXCLUDED_PARTS or any(part.endswith(".egg-info") for part in relative.parts):
        return True
    if _path_is_external(relative):
        return True
    try:
        absolute = (root / relative).resolve()
        output = output_dir.resolve()
        if absolute == output or output in absolute.parents:
            return True
    except OSError:
        return True
    if relative.name in {".DS_Store", "release-manifest.json", "component-inventory.json"}:
        # Existing generated files are recreated from source metadata below.
        if relative.parts[:1] == ("release",):
            return True
    return False


def source_files(root: Path, output_dir: Path) -> Tuple[List[Path], List[str]]:
    files: List[Path] = []
    excluded_external: set = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() and not path.exists():
            continue
        relative = path.relative_to(root)
        if _path_is_external(relative):
            for index, part in enumerate(relative.parts):
                if part.lower() in EXTERNAL_COMPONENTS:
                    excluded_external.add(Path(*relative.parts[: index + 1]).as_posix())
                    break
            continue
        if _path_is_excluded(relative, output_dir, root):
            continue
        files.append(path)
    return files, sorted(excluded_external)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
    else:
        shutil.copyfile(source, destination)
        shutil.copystat(source, destination, follow_symlinks=False)


def _category(relative: str) -> str:
    path = Path(relative)
    parts = {part.lower() for part in path.parts}
    lower_name = path.name.lower()
    if (
        lower_name.startswith(("license", "notice", "copying"))
        or "notices" in parts
        or lower_name in {"third-party-notices.md", "third_party_notices.md"}
    ):
        return "notices"
    if "installer" in parts or "installers" in parts or lower_name.startswith("install"):
        return "installers"
    if "asset" in parts or "assets" in parts or "static" in parts:
        return "assets"
    if "example" in parts or "examples" in parts:
        return "examples"
    if "doc" in parts or "docs" in parts or path.suffix.lower() in {".md", ".rst", ".adoc"}:
        return "docs"
    if path.suffix.lower() in {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".sh",
    }:
        return "code"
    return "code"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _link_digest(path: Path) -> str:
    if path.is_symlink():
        return hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    return _sha256(path)


def _file_records(stage: Path, package_root_name: str) -> List[Dict[str, Any]]:
    package_root = stage / package_root_name
    records: List[Dict[str, Any]] = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(package_root).as_posix()
        if relative == "release/release-manifest.json":
            # A manifest cannot contain a stable hash of itself.  It is identified by
            # manifest_path below and is intentionally excluded from this file list.
            continue
        mode = path.lstat().st_mode
        records.append(
            {
                "path": relative,
                "category": _category(relative),
                "size": path.lstat().st_size,
                "sha256": _link_digest(path),
                "mode": "0755" if mode & 0o111 else "0644",
            }
        )
    return records


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalized_tarinfo(info: tarfile.TarInfo, epoch: int) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = epoch
    info.pax_headers = {}
    if info.isdir():
        info.mode = 0o755
    elif info.isfile():
        info.mode = 0o755 if info.mode & 0o111 else 0o644
    return info


def _make_archive(stage: Path, package_root_name: str, archive: Path, epoch: int) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=epoch, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                package_root = stage / package_root_name
                members = [package_root] + sorted(
                    package_root.rglob("*"), key=lambda item: item.relative_to(stage).as_posix()
                )
                for member in members:
                    archive_name = member.relative_to(stage).as_posix()
                    info = _normalized_tarinfo(tar.gettarinfo(str(member), arcname=archive_name), epoch)
                    if info.isfile():
                        with member.open("rb") as handle:
                            tar.addfile(info, handle)
                    else:
                        tar.addfile(info)


def build_release(
    repo_root: Path,
    output_dir: Path,
    version: str,
    epoch: Optional[int] = None,
    lock_path: Optional[Path] = None,
) -> Dict[str, Path]:
    root = repo_root.resolve()
    output = output_dir.resolve()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version must be an exact semantic version: %s" % version)
    requested_lock = lock_path
    if requested_lock is not None and not requested_lock.is_absolute():
        requested_lock = root / requested_lock
    selected_lock = (requested_lock or default_lock_path(root)).resolve()
    lock = load_lock(selected_lock)
    reproducible_epoch = source_date_epoch(root, epoch)
    files, excluded_external = source_files(root, output)
    findings = scan_paths(root, files)
    if findings:
        formatted = ", ".join("%s:%d" % (path, line) for path, line, _ in findings)
        raise ValueError("secret scan blocked packaging (%s)" % formatted)

    archive_name = ARCHIVE_NAME % version
    checksum_name = archive_name + ".sha256"
    package_root_name = archive_name[:-7]  # strip .tar.gz
    output.mkdir(parents=True, exist_ok=True)
    for old in (output / archive_name, output / checksum_name, output / "release-manifest.json", output / "component-inventory.json"):
        if old.exists():
            old.unlink()

    with tempfile.TemporaryDirectory(prefix=".phicad-package-") as temporary:
        stage = Path(temporary)
        package_root = stage / package_root_name
        for source in files:
            relative = source.relative_to(root)
            _copy_file(source, package_root / relative)

        inventory = build_inventory(root, version, selected_lock)
        inventory["vendored_component_paths"] = excluded_external
        _write_json(package_root / "release" / "component-inventory.json", inventory)

        categories: Dict[str, List[str]] = {name: [] for name in LAYOUT_CONTRACT}
        for record in _file_records(stage, package_root_name):
            categories[record["category"]].append(record["path"])
        manifest: Dict[str, Any] = {
            "schema_version": 1,
            "manifest_type": "phicad-platform-developer-preview",
            "release": {
                "name": "PhiCad Platform",
                "version": version,
                "source_revision": _git_output(root, "rev-parse", "HEAD"),
                "source_date_epoch": reproducible_epoch,
            },
            "archive": {
                "filename": archive_name,
                "sha256": None,
                "checksum_sidecar": checksum_name,
            },
            "lock": {
                "path": selected_lock.relative_to(root).as_posix(),
                "sha256": _sha256(selected_lock),
            },
            "external_components": [
                {
                    "name": component["name"],
                    "product_surface": component.get("product_surface"),
                    "product_surfaces": component.get("product_surfaces")
                    or ([component["product_surface"]] if component.get("product_surface") else []),
                    "version": component["version"],
                    "pin": component["pin"],
                    "source": component["source"],
                    "upstream": component.get("upstream"),
                    "additional_packages": component.get("additional_packages", {}),
                    "vendored": False,
                }
                for component in sorted(lock["components"], key=lambda item: item["name"].lower())
            ],
            "external_component_paths_excluded": excluded_external,
            "layout_contract": {
                name: {"description": description, "present": bool(categories[name]), "paths": categories[name]}
                for name, description in LAYOUT_CONTRACT.items()
            },
            "manifest_path": "release/release-manifest.json",
            "component_inventory_path": "release/component-inventory.json",
            "files": _file_records(stage, package_root_name),
        }
        _write_json(package_root / "release" / "release-manifest.json", manifest)
        archive = output / archive_name
        _make_archive(stage, package_root_name, archive, reproducible_epoch)

    archive_digest = _sha256(archive)
    manifest["archive"]["sha256"] = archive_digest
    _write_json(output / "release-manifest.json", manifest)
    _write_json(output / "component-inventory.json", inventory)
    (output / checksum_name).write_text("%s  %s\n" % (archive_digest, archive_name), encoding="utf-8")
    return {
        "archive": archive,
        "checksum": output / checksum_name,
        "manifest": output / "release-manifest.json",
        "inventory": output / "component-inventory.json",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("release/dist"))
    parser.add_argument("--version", default=os.environ.get("RELEASE_VERSION", "0.1.0-dev.1"))
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--lock", type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_release(args.repo_root, args.output_dir, args.version, args.source_date_epoch, args.lock)
    except (OSError, ValueError) as exc:
        print("release packaging: ERROR: %s" % exc, file=sys.stderr)
        return 1
    for label in ("archive", "checksum", "manifest", "inventory"):
        print("%s: %s" % (label, result[label]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
