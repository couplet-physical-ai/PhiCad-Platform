"""Small, serialisable contracts shared by the CLI and orchestrator.

The contracts are intentionally boring dataclasses.  A manifest is an
interchange record, not an object graph and not an agent protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

# The current architecture has two checker origins. PhiCad Studio and Verify
# are views of the same KiCad-native authority, so they must not manufacture
# separate diagnostic lanes for the same engine.
DIAGNOSTIC_ORIGINS = ("tscircuit", "kicad")
DIAGNOSTIC_STATUSES = ("not-run", "carried-input", "reported", "passed", "failed", "unavailable")
APPROVAL_STATES = ("pending", "approved", "rejected")
SEVERITIES = ("errors", "warnings", "info")


def _as_nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("%s must be a non-negative integer" % field_name)
    return value


@dataclass(frozen=True)
class DiagnosticCounts:
    """Counts emitted by one independent diagnostic origin."""

    errors: int = 0
    warnings: int = 0
    info: int = 0

    def __post_init__(self) -> None:
        for name in SEVERITIES:
            _as_nonnegative_int(getattr(self, name), name)

    @property
    def total(self) -> int:
        return self.errors + self.warnings + self.info

    def to_dict(self) -> Dict[str, int]:
        return {name: getattr(self, name) for name in SEVERITIES}

    @classmethod
    def from_mapping(cls, value: Any) -> "DiagnosticCounts":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ValueError("diagnostic counts must be an object")
        # Accept singular spellings in Verify output, but emit only the
        # canonical plural spelling in a manifest.
        return cls(
            errors=_as_nonnegative_int(value.get("errors", value.get("error", 0)), "errors"),
            warnings=_as_nonnegative_int(value.get("warnings", value.get("warning", 0)), "warnings"),
            info=_as_nonnegative_int(value.get("info", value.get("infos", 0)), "info"),
        )


@dataclass(frozen=True)
class ArtifactRecord:
    """A generated artifact and the digest of the bytes that were checked."""

    kind: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.kind or not self.kind.strip():
            raise ValueError("artifact kind must not be empty")
        if not self.path or Path(self.path).is_absolute():
            raise ValueError("artifact path must be a non-empty relative path")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("artifact sha256 must be a lowercase SHA-256 digest")

    def to_dict(self) -> Dict[str, str]:
        return {"kind": self.kind, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class VerifyLimits:
    timeout_seconds: float = 60.0
    max_source_bytes: int = 2 * 1024 * 1024
    max_circuit_json_bytes: int = 32 * 1024 * 1024
    max_circuit_json_elements: int = 100_000
    max_stdout_bytes: int = 1024 * 1024
    max_stderr_bytes: int = 1024 * 1024
    max_result_bytes: int = 1024 * 1024
    max_output_files: int = 256
    max_output_bytes: int = 512 * 1024 * 1024
    terminate_grace_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.terminate_grace_seconds <= 0:
            raise ValueError("timeouts must be positive")
        for name in (
            "max_source_bytes",
            "max_circuit_json_bytes",
            "max_circuit_json_elements",
            "max_stdout_bytes",
            "max_stderr_bytes",
            "max_result_bytes",
            "max_output_files",
            "max_output_bytes",
        ):
            if isinstance(getattr(self, name), bool) or getattr(self, name) <= 0:
                raise ValueError("%s must be positive" % name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_circuit_json_bytes": self.max_circuit_json_bytes,
            "max_circuit_json_elements": self.max_circuit_json_elements,
            "max_output_bytes": self.max_output_bytes,
            "max_output_files": self.max_output_files,
            "max_result_bytes": self.max_result_bytes,
            "max_source_bytes": self.max_source_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
            "max_stdout_bytes": self.max_stdout_bytes,
            "terminate_grace_seconds": self.terminate_grace_seconds,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class VerifyCliConfig:
    """Exact argv and resource policy for one Verify invocation."""

    command: Tuple[str, ...]
    result_file: str = "verify-result.json"
    limits: VerifyLimits = field(default_factory=VerifyLimits)
    env_allowlist: Tuple[str, ...] = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL")
    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.command or any(not isinstance(part, str) or not part for part in self.command):
            raise ValueError("verify command must be a non-empty argv list")
        result = Path(self.result_file)
        if result.is_absolute() or ".." in result.parts:
            raise ValueError("result_file must stay inside the fresh output directory")
        for name in self.env_allowlist:
            if not name or "=" in name:
                raise ValueError("invalid environment allowlist entry")
        for name, value in self.environment.items():
            if not isinstance(name, str) or not isinstance(value, str) or not name:
                raise ValueError("configured environment must be string-to-string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": list(self.command),
            "env_allowlist": list(self.env_allowlist),
            "limits": self.limits.to_dict(),
            "result_file": self.result_file,
        }


@dataclass(frozen=True)
class PlatformConfig:
    """Resolved platform configuration; paths are made explicit in manifests."""

    verify: VerifyCliConfig
    tool_versions: Mapping[str, str]
    versions_lock_path: Optional[str] = None
    config_path: Optional[str] = None
    apply_executable: Optional[str] = None

    def __post_init__(self) -> None:
        for name, version in self.tool_versions.items():
            if not isinstance(name, str) or not name or not isinstance(version, str) or not version.strip():
                raise ValueError("tool_versions must contain non-empty strings")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_path": self.config_path,
            "apply_executable": self.apply_executable,
            "tool_versions": dict(sorted(self.tool_versions.items())),
            "verify": self.verify.to_dict(),
            "versions_lock_path": self.versions_lock_path,
        }


@dataclass(frozen=True)
class BuildCheckRequest:
    source: Path
    circuit_json: Path
    output_dir: Path
    manifest_path: Path
    design_id: str
    studio_revision: str
    studio_path: Optional[Path] = None
    studio_hash: Optional[str] = None
    approval_state: str = "pending"

    def __post_init__(self) -> None:
        if not self.design_id.strip():
            raise ValueError("design_id must not be empty")
        if not self.studio_revision.strip():
            raise ValueError("studio_revision must not be empty")
        if self.studio_path is None and self.studio_hash is None:
            raise ValueError("one of studio_path or studio_hash is required")
        if self.studio_hash is not None:
            valid_hash = len(self.studio_hash) == 64 and not any(
                char not in "0123456789abcdef" for char in self.studio_hash
            )
            if not valid_hash:
                raise ValueError("studio_hash must be a lowercase SHA-256 digest")
        if self.approval_state not in APPROVAL_STATES:
            raise ValueError("approval_state must be one of %s" % (", ".join(APPROVAL_STATES),))


@dataclass(frozen=True)
class NativeArtifactEvidence:
    revision: str
    sha256: str
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {"path": self.path, "revision": self.revision, "sha256": self.sha256}


# Python constructor compatibility only; V3 serializes native_artifact.
StudioEvidence = NativeArtifactEvidence
