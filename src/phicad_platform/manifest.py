"""Versioned, hash-addressed design manifests.

Manifest JSON is canonicalised before its self-hash is calculated.  This keeps
verification independent of dictionary insertion order and makes the output
suitable for review or signing by a higher-level workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .contracts import (
    APPROVAL_STATES,
    DIAGNOSTIC_ORIGINS,
    DIAGNOSTIC_STATUSES,
    ArtifactRecord,
    DiagnosticCounts,
    StudioEvidence,
)

# V3 names the single native authority and records apply state. V2 remains readable.
MANIFEST_SCHEMA_VERSION = 3
V2_COMPATIBILITY_NOTE = (
    "V2 compatibility: historical studio fields describe the native artifact; "
    "native_apply defaulted to unavailable-v1 (no apply evidence in V2)."
)
_SHA256_LENGTH = 64


class ManifestError(ValueError):
    """The manifest is malformed or its evidence does not verify."""


def _reject_non_json_constant(value: str) -> None:
    raise ValueError("non-standard JSON constant: %s" % value)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def sha256_path(path: Path) -> str:
    """Hash a file or a directory without depending on filesystem order."""
    path = Path(path)
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise ManifestError("evidence path does not exist: %s" % path)

    digest = hashlib.sha256()
    files = (item for item in path.rglob("*") if item.is_file())
    for child in sorted(files, key=lambda p: p.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        data_digest = sha256_file(child).encode("ascii")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(data_digest)
    return digest.hexdigest()


def _require_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise ManifestError("%s must be a SHA-256 digest" % name)
    if any(char not in "0123456789abcdef" for char in value):
        raise ManifestError("%s must be a lowercase SHA-256 digest" % name)
    return value


def _relative_artifact_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute() or not path or ".." in candidate.parts:
        raise ManifestError("artifact path must be relative and stay in the output directory: %s" % path)
    return candidate.as_posix()


@dataclass(frozen=True)
class NativeApply:
    status: str = "unavailable-v1"
    plan_hash: Optional[str] = None
    plan_path: Optional[str] = None
    base_revision: Optional[str] = None
    applied_revision: Optional[str] = None
    undo_entries: int = 0
    rejections: Tuple[Mapping[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in ("unavailable-v1", "planned", "applied", "rejected"):
            raise ManifestError("invalid native_apply status")
        if self.plan_hash is not None:
            _require_sha256(self.plan_hash, "native_apply.plan_hash")
        if self.plan_path is not None:
            if not isinstance(self.plan_path, str):
                raise ManifestError("native_apply.plan_path must be a relative path or null")
            _relative_artifact_path(self.plan_path)
        for name in ("base_revision", "applied_revision"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ManifestError("native_apply.%s must be a non-empty revision or null" % name)
        if type(self.undo_entries) is not int or self.undo_entries < 0:
            raise ManifestError("native_apply.undo_entries must be a non-negative integer")
        if self.status == "applied":
            if self.applied_revision is None or self.undo_entries != 1:
                raise ManifestError("applied requires applied_revision and exactly one undo entry")
        elif self.applied_revision is not None or self.undo_entries != 0:
            raise ManifestError("non-applied status cannot claim an applied revision or undo entry")
        if not isinstance(self.rejections, (list, tuple)):
            raise ManifestError("native_apply.rejections must be an array")
        for rejection in self.rejections:
            if not isinstance(rejection, Mapping) or set(rejection) != {"code", "element", "detail"}:
                raise ManifestError("native_apply rejection requires code, element and detail")
            if any(not isinstance(value, str) or not value for value in rejection.values()):
                raise ManifestError("native_apply rejection fields must be non-empty strings")
        object.__setattr__(self, "rejections", tuple(dict(r) for r in self.rejections))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status, "plan_hash": self.plan_hash, "plan_path": self.plan_path,
            "base_revision": self.base_revision, "applied_revision": self.applied_revision,
            "undo_entries": self.undo_entries, "rejections": [dict(r) for r in self.rejections],
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "NativeApply":
        if not isinstance(value, Mapping) or set(value) != set(cls().to_dict()):
            raise ManifestError("native_apply must contain exactly the V3 block fields")
        return cls(**value)


def native_tool_versions(versions: Mapping[str, str]) -> Dict[str, str]:
    """Collapse historical view roles without hiding contradictory pins."""
    result = dict(versions)
    pins = {result.pop(name) for name in ("phicad", "phicad-studio", "phicad-verify") if name in result}
    if len(pins) > 1:
        raise ManifestError("native PhiCad tool roles have conflicting versions")
    if pins:
        result["phicad"] = pins.pop()
    return result


@dataclass(frozen=True)
class DesignManifest:
    """All evidence needed to identify one deterministic design check."""

    design_id: str
    source_hash: str
    circuit_json_hash: str
    native_artifact: StudioEvidence
    artifacts: Tuple[ArtifactRecord, ...]
    tool_versions: Mapping[str, str]
    diagnostics: Mapping[str, DiagnosticCounts]
    diagnostic_status: Mapping[str, str] = None  # type: ignore[assignment]
    approval_state: str = "pending"
    source_path: Optional[str] = None
    circuit_json_path: Optional[str] = None
    configuration: Mapping[str, Any] = None  # type: ignore[assignment]
    manifest_hash: Optional[str] = None
    manifest_version: int = MANIFEST_SCHEMA_VERSION
    native_apply: NativeApply = field(default_factory=NativeApply)
    compatibility_notes: Tuple[str, ...] = ()

    @property
    def studio(self) -> StudioEvidence:
        """Legacy Python accessor; V3 wire fields use native_artifact."""
        return self.native_artifact

    def __post_init__(self) -> None:
        if type(self.manifest_version) is not int or self.manifest_version not in (2, 3):
            raise ManifestError("unsupported manifest version: %s" % self.manifest_version)
        if not self.design_id or not self.design_id.strip():
            raise ManifestError("design_id must not be empty")
        _require_sha256(self.source_hash, "source_hash")
        _require_sha256(self.circuit_json_hash, "circuit_json_hash")
        if not isinstance(self.native_apply, NativeApply):
            raise ManifestError("native_apply must be a validated NativeApply block")
        if self.manifest_version == 3:
            object.__setattr__(self, "tool_versions", native_tool_versions(self.tool_versions))
        _require_sha256(self.studio.sha256, "native_artifact.sha256")
        if not self.studio.revision or not self.studio.revision.strip():
            raise ManifestError("studio revision must not be empty")
        if self.approval_state not in APPROVAL_STATES:
            raise ManifestError("invalid approval_state: %s" % self.approval_state)
        if self.configuration is None:
            object.__setattr__(self, "configuration", {})
        for origin in DIAGNOSTIC_ORIGINS:
            if origin not in self.diagnostics:
                raise ManifestError("missing diagnostic origin: %s" % origin)
        unknown_origins = set(self.diagnostics) - set(DIAGNOSTIC_ORIGINS)
        if unknown_origins:
            raise ManifestError("unknown diagnostic origins: %s" % ", ".join(sorted(unknown_origins)))
        if self.diagnostic_status is None:
            object.__setattr__(
                self,
                "diagnostic_status",
                {origin: "reported" for origin in DIAGNOSTIC_ORIGINS},
            )
        if set(self.diagnostic_status) != set(DIAGNOSTIC_ORIGINS):
            raise ManifestError("diagnostic_status must name every diagnostic origin exactly once")
        for origin, status in self.diagnostic_status.items():
            if status not in DIAGNOSTIC_STATUSES:
                raise ManifestError("invalid diagnostic status for %s: %s" % (origin, status))
        seen_kinds = set()
        for artifact in self.artifacts:
            if artifact.kind in seen_kinds:
                raise ManifestError("duplicate artifact kind: %s" % artifact.kind)
            seen_kinds.add(artifact.kind)
        for name, version in self.tool_versions.items():
            if not isinstance(name, str) or not name or not isinstance(version, str) or not version.strip():
                raise ManifestError("tool_versions must contain exact non-empty strings")

    @property
    def artifact_hashes(self) -> Dict[str, str]:
        return {artifact.kind: artifact.sha256 for artifact in self.artifacts}

    def _payload(self) -> Dict[str, Any]:
        # Keep the important hashes at the top level.  The paths are evidence
        # pointers only; artifact paths intentionally remain relative.
        payload = {
            "approval": {"state": self.approval_state},
            "approval_state": self.approval_state,
            "artifact_hashes": dict(sorted(self.artifact_hashes.items())),
            "artifacts": [
                artifact.to_dict()
                for artifact in sorted(self.artifacts, key=lambda item: (item.kind, item.path))
            ],
            "circuit_json": {"hash": self.circuit_json_hash, "path": self.circuit_json_path},
            "circuit_json_hash": self.circuit_json_hash,
            "circuit_json_path": self.circuit_json_path,
            "configuration": self.configuration,
            "design_id": self.design_id,
            "diagnostic_status": {
                origin: self.diagnostic_status[origin] for origin in DIAGNOSTIC_ORIGINS
            },
            "diagnostics": {
                origin: self.diagnostics[origin].to_dict() for origin in DIAGNOSTIC_ORIGINS
            },
            "manifest_version": self.manifest_version,
            "source": {"hash": self.source_hash, "path": self.source_path},
            "source_hash": self.source_hash,
            "source_path": self.source_path,
            "tool_versions": dict(sorted(self.tool_versions.items())),
        }
        # Verify V2 using its original canonical vocabulary, not a silently rehashed migration.
        if self.manifest_version == 2:
            payload.update(studio=self.studio.to_dict(), studio_hash=self.studio.sha256,
                           studio_path=self.studio.path, studio_revision=self.studio.revision)
        else:
            payload.update(native_artifact=self.native_artifact.to_dict(),
                           native_artifact_hash=self.native_artifact.sha256,
                           native_artifact_path=self.native_artifact.path,
                           native_revision=self.native_artifact.revision,
                           native_apply=self.native_apply.to_dict())
        return payload

    def calculated_hash(self) -> str:
        return sha256_bytes(canonical_json_bytes(self._payload()))

    def to_dict(self) -> Dict[str, Any]:
        payload = self._payload()
        payload["manifest_hash"] = self.manifest_hash or self.calculated_hash()
        return payload


def create_manifest(
    *,
    design_id: str,
    source_hash: str,
    circuit_json_hash: str,
    studio_revision: Optional[str] = None,
    studio_hash: Optional[str] = None,
    native_revision: Optional[str] = None,
    native_artifact_hash: Optional[str] = None,
    native_artifact_path: Optional[str] = None,
    native_apply: Optional[NativeApply] = None,
    artifacts: Iterable[ArtifactRecord],
    tool_versions: Mapping[str, str],
    diagnostics: Mapping[str, DiagnosticCounts],
    diagnostic_status: Optional[Mapping[str, str]] = None,
    approval_state: str = "pending",
    source_path: Optional[str] = None,
    circuit_json_path: Optional[str] = None,
    studio_path: Optional[str] = None,
    configuration: Optional[Mapping[str, Any]] = None,
) -> DesignManifest:
    manifest = DesignManifest(
        design_id=design_id,
        source_hash=source_hash,
        circuit_json_hash=circuit_json_hash,
        native_artifact=StudioEvidence(
            revision=_alias(native_revision, studio_revision, "native_revision"),
            sha256=_alias(native_artifact_hash, studio_hash, "native_artifact_hash"),
            path=_alias(native_artifact_path, studio_path, "native_artifact_path"),
        ),
        native_apply=native_apply or NativeApply(),
        artifacts=tuple(artifacts),
        tool_versions=dict(tool_versions),
        diagnostics=dict(diagnostics),
        diagnostic_status=dict(diagnostic_status) if diagnostic_status is not None else None,
        approval_state=approval_state,
        source_path=source_path,
        circuit_json_path=circuit_json_path,
        configuration=dict(configuration or {}),
    )
    return replace(manifest, manifest_hash=manifest.calculated_hash())


def _alias(current: Any, legacy: Any, label: str) -> Any:
    if current is not None and legacy is not None and current != legacy:
        raise ManifestError("conflicting legacy and native value for %s" % label)
    return current if current is not None else legacy


def _manifest_from_dict(data: Mapping[str, Any]) -> DesignManifest:
    if not isinstance(data, Mapping):
        raise ManifestError("manifest root must be an object")
    raw_artifacts = data.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise ManifestError("artifacts must be an array")
    artifacts = []
    for raw in raw_artifacts:
        if not isinstance(raw, Mapping):
            raise ManifestError("each artifact must be an object")
        artifacts.append(
            ArtifactRecord(
                kind=str(raw.get("kind", "")),
                path=_relative_artifact_path(str(raw.get("path", ""))),
                sha256=_require_sha256(raw.get("sha256"), "artifact.sha256"),
            )
        )
    raw_diagnostics = data.get("diagnostics")
    if not isinstance(raw_diagnostics, Mapping):
        raise ManifestError("diagnostics must be an object")
    try:
        diagnostics = {
            origin: DiagnosticCounts.from_mapping(raw_diagnostics.get(origin))
            for origin in DIAGNOSTIC_ORIGINS
        }
    except (TypeError, ValueError) as exc:
        raise ManifestError("invalid diagnostic counts: %s" % exc)
    if set(raw_diagnostics) != set(DIAGNOSTIC_ORIGINS):
        raise ManifestError("diagnostics must name every diagnostic origin exactly once")
    unknown = set(raw_diagnostics) - set(DIAGNOSTIC_ORIGINS)
    if unknown:
        raise ManifestError("unknown diagnostic origins: %s" % ", ".join(sorted(unknown)))
    raw_diagnostic_status = data.get("diagnostic_status")
    if raw_diagnostic_status is None:
        diagnostic_status = {origin: "reported" for origin in DIAGNOSTIC_ORIGINS}
    elif isinstance(raw_diagnostic_status, Mapping):
        diagnostic_status = {str(origin): str(status) for origin, status in raw_diagnostic_status.items()}
    else:
        raise ManifestError("diagnostic_status must be an object")
    raw_config = data.get("configuration", {})
    if not isinstance(raw_config, Mapping):
        raise ManifestError("configuration must be an object")
    raw_source = data.get("source", {})
    if not isinstance(raw_source, Mapping):
        raise ManifestError("source must be an object")
    raw_circuit = data.get("circuit_json", {})
    if not isinstance(raw_circuit, Mapping):
        raise ManifestError("circuit_json must be an object")
    legacy = data.get("manifest_version") == 2
    artifact_key = "studio" if legacy else "native_artifact"
    hash_key = "studio_hash" if legacy else "native_artifact_hash"
    path_key = "studio_path" if legacy else "native_artifact_path"
    revision_key = "studio_revision" if legacy else "native_revision"
    raw_studio = data.get(artifact_key, {})
    if not isinstance(raw_studio, Mapping):
        raise ManifestError("%s must be an object" % artifact_key)
    native_apply = NativeApply() if legacy else NativeApply.from_mapping(data.get("native_apply"))
    raw_approval = data.get("approval", {})
    if not isinstance(raw_approval, Mapping):
        raise ManifestError("approval must be an object")
    raw_tool_versions = data.get("tool_versions", {})
    if not isinstance(raw_tool_versions, Mapping):
        raise ManifestError("tool_versions must be an object")
    try:
        manifest = DesignManifest(
            design_id=str(data.get("design_id", "")),
            source_hash=_require_sha256(data.get("source_hash", raw_source.get("hash")), "source_hash"),
            circuit_json_hash=_require_sha256(
                data.get("circuit_json_hash", raw_circuit.get("hash")), "circuit_json_hash"
            ),
            native_artifact=StudioEvidence(
                revision=str(data.get(revision_key, raw_studio.get("revision", ""))),
                sha256=_require_sha256(
                    data.get(hash_key, raw_studio.get("sha256", raw_studio.get("hash"))), hash_key,
                ),
                path=data.get(path_key, raw_studio.get("path")),
            ),
            native_apply=native_apply,
            compatibility_notes=(V2_COMPATIBILITY_NOTE,) if legacy else (),
            artifacts=tuple(artifacts),
            tool_versions=raw_tool_versions,
            diagnostics=diagnostics,
            diagnostic_status=diagnostic_status,
            approval_state=str(data.get("approval_state", raw_approval.get("state", ""))),
            source_path=data.get("source_path", raw_source.get("path")),
            circuit_json_path=data.get("circuit_json_path", raw_circuit.get("path")),
            configuration=dict(raw_config),
            manifest_hash=_require_sha256(data.get("manifest_hash"), "manifest_hash"),
            manifest_version=data.get("manifest_version"),
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise ManifestError("invalid manifest fields: %s" % exc)
    expected_hashes = data.get("artifact_hashes", {})
    if expected_hashes != manifest.artifact_hashes:
        raise ManifestError("artifact_hashes does not match artifacts")
    raw_payload = dict(data)
    raw_payload.pop("manifest_hash", None)
    if canonical_json_bytes(raw_payload) != canonical_json_bytes(manifest._payload()):
        raise ManifestError("manifest fields do not match canonical schema content")
    if manifest.manifest_hash != manifest.calculated_hash():
        raise ManifestError("manifest_hash does not match canonical manifest content")
    return manifest


def load_manifest(path: Path, max_bytes: int = 4 * 1024 * 1024) -> DesignManifest:
    path = Path(path)
    if not path.is_file():
        raise ManifestError("manifest does not exist: %s" % path)
    if path.stat().st_size > max_bytes:
        raise ManifestError("manifest exceeds the %d-byte limit" % max_bytes)
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_non_json_constant
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ManifestError("cannot read manifest: %s" % exc)
    return _manifest_from_dict(data)


@dataclass(frozen=True)
class ManifestVerification:
    valid: bool
    path: str
    errors: Tuple[str, ...] = ()
    manifest: Optional[DesignManifest] = None

    def __bool__(self) -> bool:
        return self.valid

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"errors": list(self.errors), "path": self.path, "valid": self.valid}
        if self.manifest is not None:
            result["manifest"] = self.manifest.to_dict()
            result["compatibility_notes"] = list(self.manifest.compatibility_notes)
            result["native_apply"] = self.manifest.native_apply.to_dict()
        return result


def _verify_evidence(path: Path, expected: str, label: str) -> Optional[str]:
    if not path.exists():
        return "%s is missing: %s" % (label, path)
    try:
        actual = sha256_path(path)
    except (OSError, ManifestError) as exc:
        return "%s cannot be hashed: %s" % (label, exc)
    if actual != expected:
        return "%s is stale (expected %s, got %s)" % (label, expected, actual)
    return None


def verify_manifest(path: Path, verify_files: bool = True) -> ManifestVerification:
    path = Path(path)
    try:
        manifest = load_manifest(path)
    except (ManifestError, TypeError, ValueError, AttributeError, KeyError, OSError) as exc:
        return ManifestVerification(valid=False, path=str(path), errors=(str(exc),))
    if not verify_files:
        return ManifestVerification(valid=True, path=str(path), manifest=manifest)

    errors: List[str] = []

    def evidence_path(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else path.parent / candidate

    if manifest.source_path:
        error = _verify_evidence(evidence_path(manifest.source_path), manifest.source_hash, "source")
        if error:
            errors.append(error)
    if manifest.circuit_json_path:
        error = _verify_evidence(evidence_path(manifest.circuit_json_path), manifest.circuit_json_hash, "Circuit JSON")
        if error:
            errors.append(error)
    if manifest.studio.path:
        error = _verify_evidence(evidence_path(manifest.studio.path), manifest.studio.sha256, "native artifact")
        if error:
            errors.append(error)

    configured_root = manifest.configuration.get("artifact_root") if manifest.configuration else None
    root = evidence_path(configured_root).resolve() if configured_root else path.parent.resolve()
    for artifact in manifest.artifacts:
        artifact_path = (root / artifact.path).resolve()
        try:
            artifact_path.relative_to(root)
        except ValueError:
            errors.append("artifact escapes manifest directory: %s" % artifact.path)
            continue
        error = _verify_evidence(artifact_path, artifact.sha256, "artifact %s" % artifact.kind)
        if error:
            errors.append(error)
    if manifest.native_apply.plan_path:
        plan_path = path.parent / manifest.native_apply.plan_path
        try:
            if plan_path.is_symlink() or not plan_path.is_file() or plan_path.stat().st_size > 1024 * 1024:
                raise ManifestError("apply plan must be a bounded regular file")
            plan_path.resolve().relative_to(path.parent.resolve())
            plan = json.loads(plan_path.read_text(encoding="utf-8"), parse_constant=_reject_non_json_constant)
            from .orchestrator import _parse_apply_plan
            validated = _parse_apply_plan(plan_path, manifest.circuit_json_hash,
                                          Path(plan["project"]["path"]), 0 if plan["status"] == "planned" else 3)
            if (validated["plan_hash"] != manifest.native_apply.plan_hash
                    or validated["project"]["base_revision"] != manifest.native_apply.base_revision
                    or validated["rejections"] != list(manifest.native_apply.rejections)):
                raise ManifestError("native_apply does not match the apply plan")
            if manifest.native_apply.status != "applied" and validated["status"] != manifest.native_apply.status:
                raise ManifestError("native_apply status does not match the apply plan")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            errors.append("apply plan is stale or invalid: %s" % exc)
    return ManifestVerification(valid=not errors, path=str(path), errors=tuple(errors), manifest=manifest)


def write_manifest(manifest: DesignManifest, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = path.with_name(".%s.tmp" % path.name)
    try:
        temporary.write_text(data, encoding="utf-8")
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()
