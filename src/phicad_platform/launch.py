"""Manifest-bound cross-view launch handoffs for PhiCad Platform.

A launch is a validated local handoff, not synchronization.  Requests carry a
manifest identity and target view; they never carry commands or credentials.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from .manifest import DesignManifest, ManifestError, load_manifest, sha256_file, verify_manifest

LAUNCH_SCHEMA = "io.github.couplet-physical-ai.phicad.platform-launch/v3"
TARGET_VIEWS = ("phi", "studio", "circuit-source", "verify", "docs", "preview")
SOURCE_VIEWS = TARGET_VIEWS + ("platform",)
MAX_URI_BYTES = 16 * 1024


class LaunchError(RuntimeError):
    """A stable, user-actionable launch refusal."""

    def __init__(self, code: str, message: str, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "details": self.details, "message": self.message}


@dataclass(frozen=True)
class LaunchPlan:
    request: Mapping[str, Any]
    command: Tuple[str, ...]
    cwd: str
    available: bool
    unavailable_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "command": list(self.command),
            "cwd": self.cwd,
            "request": dict(self.request),
            "unavailable_reason": self.unavailable_reason,
        }


def _require_target(value: str, *, source: bool = False) -> str:
    allowed = SOURCE_VIEWS if source else TARGET_VIEWS
    if value not in allowed:
        raise LaunchError("invalid_view", "view must be one of: %s" % ", ".join(allowed))
    return value


def _manifest_identity(path: Path, expected_sha256: Optional[str]) -> Tuple[DesignManifest, str]:
    path = path.expanduser().absolute()
    if not path.is_file() or path.is_symlink():
        raise LaunchError("manifest_missing", "manifest must be an existing regular file: %s" % path)
    try:
        file_hash = sha256_file(path)
    except (ManifestError, OSError, ValueError) as exc:
        raise LaunchError("manifest_invalid", "manifest validation failed: %s" % exc)
    if expected_sha256 is not None and expected_sha256 != file_hash:
        raise LaunchError(
            "stale_handoff",
            "manifest file hash changed; refusing to open a stale handoff",
            {"actual": file_hash, "expected": expected_sha256},
        )
    try:
        manifest = load_manifest(path)
    except (ManifestError, OSError, ValueError) as exc:
        raise LaunchError("stale_handoff", "manifest content no longer verifies: %s" % exc)
    checked = verify_manifest(path)
    if not checked.valid:
        raise LaunchError("stale_handoff", "referenced evidence changed", {"errors": list(checked.errors)})
    return manifest, file_hash


def _project_root(manifest: DesignManifest, manifest_path: Path) -> Path:
    configured = manifest.configuration.get("project_root") if manifest.configuration else None
    if isinstance(configured, str) and configured:
        candidate = Path(configured).expanduser()
        root = (candidate if candidate.is_absolute() else manifest_path.parent / candidate).resolve()
    elif manifest.source_path:
        candidate = Path(manifest.source_path).expanduser()
        source = (candidate if candidate.is_absolute() else manifest_path.parent / candidate).resolve()
        root = source if source.is_dir() else source.parent
    else:
        root = manifest_path.parent.resolve()
    if not root.is_dir():
        raise LaunchError("project_missing", "manifest project root is unavailable: %s" % root)
    return root


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise LaunchError("unsafe_path", "%s is outside the manifest project root" % label)
    if not resolved.exists():
        raise LaunchError("target_missing", "%s does not exist: %s" % (label, resolved))
    return resolved


def _safe_environment() -> Dict[str, str]:
    names = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "TERM", "SHELL")
    return {name: os.environ[name] for name in names if name in os.environ}


def _which_or_path(names: Sequence[str], candidates: Sequence[Path] = ()) -> Optional[str]:
    for name in names:
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return None


def _artifact_root(manifest: DesignManifest, manifest_path: Path) -> Path:
    configured = manifest.configuration.get("artifact_root") if manifest.configuration else None
    if isinstance(configured, str) and configured:
        candidate = Path(configured).expanduser()
        return (candidate if candidate.is_absolute() else manifest_path.parent / candidate).resolve()
    return manifest_path.parent.resolve()


def _verify_target(manifest: DesignManifest, manifest_path: Path) -> Path:
    root = _artifact_root(manifest, manifest_path)
    preferred = ("kicad-project", "kicad-pcb", "kicad-schematic", "kicad_pro", "kicad", "phicad")
    ordered = sorted(manifest.artifacts, key=lambda item: (preferred.index(item.kind) if item.kind in preferred else len(preferred), item.path))
    for artifact in ordered:
        candidate = (root / artifact.path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file() and candidate.suffix in {".kicad_pro", ".kicad_pcb", ".kicad_sch"}:
            return candidate
    raise LaunchError("target_missing", "manifest has no local KiCad artifact for PhiCad Verify")


def discover_phicad_executable(root: Path) -> Optional[str]:
    """PATH then conventional sibling checkout; never an ambient executable override."""
    package_root = Path(__file__).resolve().parents[2]
    return _which_or_path(
        ("phicad",),
        (
            package_root.parent / "PhiCad" / "phicad" / "bin" / "phicad",
            root.parent / "PhiCad" / "phicad" / "bin" / "phicad",
        ),
    )


def _phicad_open_command(target: Path, root: Path) -> Tuple[str, ...]:
    """Resolve the one native PhiCad application used by Studio and Verify."""
    phicad = discover_phicad_executable(root)
    if phicad:
        return (phicad, "open", str(target))
    installed_app = next(
        (
            candidate
            for candidate in (
                Path("/Applications/PhiCad.app"),
                Path.home() / "Applications" / "PhiCad.app",
            )
            if candidate.is_dir() and not candidate.is_symlink()
        ),
        None,
    )
    if installed_app is not None and Path("/usr/bin/open").is_file():
        return ("/usr/bin/open", "-a", str(installed_app), str(target))
    return ()


def _request(
    manifest: DesignManifest,
    manifest_path: Path,
    manifest_file_hash: str,
    target_view: str,
    source_view: str,
    focus: bool,
) -> Dict[str, Any]:
    return {
        "expected": {
            "artifact_hashes": dict(sorted(manifest.artifact_hashes.items())),
            "circuit_json_sha256": manifest.circuit_json_hash,
            "native_design_id": manifest.design_id,
            "native_revision": manifest.studio.revision,
            "native_sha256": manifest.studio.sha256,
            "source_sha256": manifest.source_hash,
        },
        "focus": bool(focus),
        "project": {
            "expected_manifest_sha256": manifest_file_hash,
            "manifest_hash": manifest.manifest_hash,
            "manifest_path": str(manifest_path),
            "project_id": manifest.design_id,
        },
        "request_id": str(uuid.uuid4()),
        "schema": LAUNCH_SCHEMA,
        "source_view": source_view,
        "target_view": target_view,
    }


def build_launch_plan(
    manifest_path: Path,
    target_view: str,
    *,
    expected_manifest_sha256: Optional[str] = None,
    source_view: str = "platform",
    focus: bool = True,
) -> LaunchPlan:
    """Validate a handoff and resolve a fixed local launch adapter."""

    target_view = _require_target(target_view)
    source_view = _require_target(source_view, source=True)
    manifest_path = manifest_path.expanduser().absolute()
    manifest, manifest_file_hash = _manifest_identity(manifest_path, expected_manifest_sha256)
    root = _project_root(manifest, manifest_path)
    request = _request(manifest, manifest_path, manifest_file_hash, target_view, source_view, focus)

    command: Tuple[str, ...]
    reason: Optional[str] = None
    if target_view == "phi":
        forca = _which_or_path(("forca",))
        phi = _which_or_path(("phi",))
        if forca and phi:
            command = (
                forca,
                "terminal",
                "create",
                "--worktree",
                "path:%s" % root,
                "--title",
                "PhiCad · Phi",
                "--command",
                "phi --name phicad-project",
            ) + (("--focus",) if focus else ())
        else:
            command = ()
            reason = "Phi and Forca must both be installed for the Phi view"
    elif target_view == "circuit-source":
        if not manifest.source_path:
            raise LaunchError("target_missing", "manifest has no Circuit Source path")
        source_path = Path(manifest.source_path)
        source = _inside(source_path if source_path.is_absolute() else manifest_path.parent / source_path,
                         root, "Circuit Source")
        forca = _which_or_path(("forca",))
        if forca:
            command = (
                forca,
                "file",
                "open",
                str(source.relative_to(root)),
                "--worktree",
                "path:%s" % root,
            )
        elif Path("/usr/bin/open").is_file():
            command = ("/usr/bin/open", str(source))
        else:
            command = ()
            reason = "no supported source-view launcher is installed"
    elif target_view == "preview":
        configured = os.environ.get("PHICAD_CIRCUIT_PREVIEW", "")
        preview = Path(configured)
        if configured and preview.is_absolute() and preview.is_file() and os.access(preview, os.X_OK):
            command = (str(preview), "--manifest", str(manifest_path),
                       "--expected-manifest-sha256", manifest_file_hash)
        else:
            command = ()
            reason = "PHICAD_CIRCUIT_PREVIEW must be an operator-configured absolute executable path"
    elif target_view in {"studio", "verify"}:
        target = _verify_target(manifest, manifest_path)
        command = _phicad_open_command(target, root)
        if not command:
            reason = "PhiCad Studio + Verify is not installed"
    else:  # docs
        package_root = Path(__file__).resolve().parents[2]
        rendered_docs = package_root / "site" / "index.html"
        docs = rendered_docs if rendered_docs.is_file() else package_root / "docs" / "index.md"
        if docs.is_file():
            if Path("/usr/bin/open").is_file():
                command = ("/usr/bin/open", str(docs))
            else:
                command = ()
                reason = "no supported local documentation launcher is installed"
        else:
            command = ()
            reason = "version-matched local documentation is not installed"

    return LaunchPlan(
        request=request,
        command=command,
        cwd=str(root),
        available=bool(command),
        unavailable_reason=reason,
    )


def execute_launch(plan: LaunchPlan, *, dry_run: bool = False) -> Mapping[str, Any]:
    """Execute a previously validated plan without a shell or inherited secrets."""

    project = plan.request["project"]
    manifest, file_hash = _manifest_identity(Path(project["manifest_path"]), project["expected_manifest_sha256"])
    current = _request(manifest, Path(project["manifest_path"]), file_hash,
                       plan.request["target_view"], plan.request["source_view"], plan.request["focus"])
    if current["project"] != project or current["expected"] != plan.request["expected"]:
        raise LaunchError("stale_handoff", "project identity, revision or artifact hash changed")
    result = plan.to_dict()
    result["executed"] = False
    if not plan.available:
        raise LaunchError("target_unavailable", plan.unavailable_reason or "target view is unavailable")
    if dry_run:
        result["dry_run"] = True
        return result
    try:
        process = subprocess.Popen(
            plan.command,
            cwd=plan.cwd,
            env=_safe_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise LaunchError("launch_failed", "could not start target view: %s" % exc)
    result["executed"] = True
    result["pid"] = process.pid
    return result


def make_deep_link(plan: LaunchPlan) -> str:
    project = plan.request["project"]
    query = urlencode(
        {
            "manifest": project["manifest_path"],
            "sha256": project["expected_manifest_sha256"],
            "source": plan.request["source_view"],
            "view": plan.request["target_view"],
        }
    )
    return "phicad://open?%s" % query


def parse_deep_link(uri: str) -> Mapping[str, Any]:
    if len(uri.encode("utf-8")) > MAX_URI_BYTES:
        raise LaunchError("invalid_uri", "launch URI exceeds the size limit")
    parsed = urlparse(uri)
    if parsed.scheme != "phicad" or parsed.netloc != "open" or parsed.path not in ("", "/"):
        raise LaunchError("invalid_uri", "expected phicad://open launch URI")
    values = parse_qs(parsed.query, strict_parsing=True)
    allowed = {"manifest", "sha256", "source", "view", "focus"}
    if set(values) - allowed or any(len(items) != 1 for items in values.values()):
        raise LaunchError("invalid_uri", "launch URI has unsupported or repeated parameters")
    for required in ("manifest", "sha256", "view"):
        if required not in values:
            raise LaunchError("invalid_uri", "launch URI is missing %s" % required)
    return {
        "expected_manifest_sha256": values["sha256"][0],
        "focus": values.get("focus", ["true"])[0].lower() not in {"0", "false", "no"},
        "manifest_path": values["manifest"][0],
        "source_view": values.get("source", ["platform"])[0],
        "target_view": values["view"][0],
    }


def open_view(
    *,
    manifest_path: str,
    target_view: str,
    expected_manifest_sha256: Optional[str] = None,
    source_view: str = "platform",
    focus: bool = True,
    dry_run: bool = False,
) -> Mapping[str, Any]:
    plan = build_launch_plan(
        Path(manifest_path),
        target_view,
        expected_manifest_sha256=expected_manifest_sha256,
        source_view=source_view,
        focus=focus,
    )
    result = dict(execute_launch(plan, dry_run=dry_run))
    result["deep_link"] = make_deep_link(plan)
    return result


def open_uri(uri: str, *, dry_run: bool = False) -> Mapping[str, Any]:
    values = dict(parse_deep_link(uri))
    values["dry_run"] = dry_run
    return open_view(**values)
