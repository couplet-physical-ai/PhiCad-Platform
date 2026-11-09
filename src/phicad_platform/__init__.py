"""Deterministic core orchestration for the PhiCad Platform preview.

Phi is the only AI harness.  This package deliberately contains no model or
agent runtime; it validates inputs, invokes the configured Verify executable,
and records reproducible design evidence.
"""

from .contracts import (
    APPROVAL_STATES,
    DIAGNOSTIC_ORIGINS,
    DIAGNOSTIC_STATUSES,
    ArtifactRecord,
    BuildCheckRequest,
    DiagnosticCounts,
    PlatformConfig,
    VerifyCliConfig,
    VerifyLimits,
)
from .manifest import (
    MANIFEST_SCHEMA_VERSION,
    DesignManifest,
    ManifestError,
    ManifestVerification,
    create_manifest,
    load_manifest,
    verify_manifest,
    write_manifest,
)
from .orchestrator import (
    BuildCheckError,
    BuildCheckResult,
    build_check,
    discover_verify_command,
    doctor,
    load_platform_config,
)

__all__ = [
    "APPROVAL_STATES",
    "DIAGNOSTIC_ORIGINS",
    "DIAGNOSTIC_STATUSES",
    "ArtifactRecord",
    "BuildCheckError",
    "BuildCheckRequest",
    "BuildCheckResult",
    "DesignManifest",
    "DiagnosticCounts",
    "MANIFEST_SCHEMA_VERSION",
    "ManifestError",
    "ManifestVerification",
    "PlatformConfig",
    "VerifyCliConfig",
    "VerifyLimits",
    "build_check",
    "create_manifest",
    "discover_verify_command",
    "doctor",
    "load_manifest",
    "load_platform_config",
    "verify_manifest",
    "write_manifest",
]

__version__ = "0.1.0.dev1"
