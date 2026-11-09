"""Command-line interface for the PhiCad Platform developer preview."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from . import __version__
from .contracts import APPROVAL_STATES, DIAGNOSTIC_ORIGINS, BuildCheckRequest, PlatformConfig, VerifyCliConfig
from .launch import LAUNCH_SCHEMA, TARGET_VIEWS, LaunchError, open_uri, open_view
from .manifest import ManifestError, verify_manifest
from .orchestrator import BuildCheckError, build_check, design_apply_plan, load_platform_config
from .orchestrator import doctor as run_doctor

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VERIFY_FAILED = 3
EXIT_MANIFEST_INVALID = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phicad-platform",
        description="Deterministic PhiCad orchestration; Phi is the only AI harness.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="verb", required=True)

    doctor = subparsers.add_parser("doctor", help="report configured tools and safety policy")
    doctor.add_argument("--config", type=Path, help="explicit phicad-platform.json")

    capabilities = subparsers.add_parser("capabilities", help="list deterministic platform capabilities")
    capabilities.add_argument("--config", type=Path, help="include the resolved configuration")

    build = subparsers.add_parser("build-check", help="run the configured PhiCad Verify CLI")
    build.add_argument("--source", type=Path, required=True, help="source design file or directory")
    build.add_argument("--circuit-json", type=Path, required=True, help="Circuit Engine JSON input")
    studio_group = build.add_mutually_exclusive_group(required=True)
    studio_group.add_argument("--native-artifact", "--native-artifact-path", "--studio", dest="studio", type=Path,
                              help="native PhiCad artifact (--studio is a legacy alias)")
    studio_group.add_argument("--native-artifact-hash", "--studio-hash", dest="studio_hash",
                              help="native artifact SHA-256 (--studio-hash is a legacy alias)")
    build.add_argument("--native-revision", "--studio-revision", dest="studio_revision", required=True,
                       help="existing native evidence revision; not an applied revision")
    build.add_argument("--output-dir", type=Path, required=True, help="empty directory reserved for this check")
    build.add_argument("--manifest", type=Path, help="manifest path (default: OUTPUT/design.manifest.json)")
    build.add_argument("--design-id", help="stable design identifier (default: source stem)")
    build.add_argument("--approval-state", choices=APPROVAL_STATES, default="pending")
    build.add_argument("--config", type=Path, help="explicit phicad-platform.json")
    build.add_argument("--verify-cli", type=Path, help="override config with this standard Verify executable")

    apply = subparsers.add_parser("apply-plan", help="plan native apply; never commit")
    apply.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    apply.add_argument("--project", type=Path, required=True)
    apply.add_argument("--output-dir", type=Path, required=True)
    apply.add_argument("--expected-revision")
    apply.add_argument("--config", type=Path)
    apply.add_argument("--commit", action="store_true", help="always refused at the Platform plan-only gate")

    manifest = subparsers.add_parser("manifest", help="work with versioned design manifests")
    manifest_subparsers = manifest.add_subparsers(dest="manifest_verb", required=True)
    verify = manifest_subparsers.add_parser("verify", help="verify manifest hash and referenced evidence")
    verify.add_argument("path", type=Path)
    verify.add_argument("--no-file-check", action="store_true", help="verify JSON/self-hash only")

    launch = subparsers.add_parser("open", help="open the same manifest-bound project in another view")
    launch.add_argument("target_view", choices=TARGET_VIEWS)
    launch.add_argument("--manifest", type=Path, required=True)
    launch.add_argument("--expected-manifest-sha256")
    launch.add_argument("--source-view", default="platform")
    launch.add_argument("--no-focus", action="store_true")
    launch.add_argument("--dry-run", action="store_true")

    launch_uri = subparsers.add_parser("open-uri", help="validate and open a phicad:// handoff")
    launch_uri.add_argument("uri")
    launch_uri.add_argument("--dry-run", action="store_true")
    return parser


def _print_json(value: Any, stream: Any = sys.stdout) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), file=stream)


def _capabilities(config: Optional[Any] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ai_harness": "Phi",
        "agent_runtime": False,
        "deterministic_json": True,
        "diagnostic_origins": list(DIAGNOSTIC_ORIGINS),
        "verbs": ["doctor", "capabilities", "build-check", "manifest verify", "open", "open-uri", "apply-plan"],
        "native_apply": {"plan_only": True, "commit": False, "tool": "design_apply_plan"},
        "cross_view_launch": {
            "schema": LAUNCH_SCHEMA,
            "targets": list(TARGET_VIEWS),
            "manifest_bound": True,
            "credentials_in_handoff": False,
            "hidden_peer_mutation": False,
        },
        "build_check": {
            "async_process": True,
            "fresh_output_directory": True,
            "no_dynamic_downloads": True,
            "shell": False,
            "process_group_termination": True,
            "minimal_allowlisted_environment": True,
        },
    }
    if config is not None:
        result["configuration"] = config.to_dict()
    return result


def _run_build(args: argparse.Namespace) -> int:
    config = load_platform_config(args.config)
    if args.verify_cli:
        command = (
            str(args.verify_cli.expanduser().resolve()),
            "verify",
            "--circuit-json",
            "{circuit_json}",
            "--output-dir",
            "{output_dir}",
            "--result",
            "{result}",
        )
        config = PlatformConfig(
            verify=VerifyCliConfig(
                command=command,
                result_file=config.verify.result_file,
                limits=config.verify.limits,
                env_allowlist=config.verify.env_allowlist,
                environment=config.verify.environment,
            ),
            tool_versions=config.tool_versions,
            versions_lock_path=config.versions_lock_path,
            config_path=config.config_path,
        )
    output_dir = args.output_dir.expanduser().resolve()
    manifest_path = (args.manifest or (output_dir / "design.manifest.json")).expanduser().resolve()
    design_id = args.design_id or args.source.stem
    request = BuildCheckRequest(
        source=args.source.expanduser().resolve(),
        circuit_json=args.circuit_json.expanduser().resolve(),
        output_dir=output_dir,
        manifest_path=manifest_path,
        design_id=design_id,
        studio_revision=args.studio_revision,
        studio_path=args.studio.expanduser().resolve() if args.studio else None,
        studio_hash=args.studio_hash,
        approval_state=args.approval_state,
    )
    result = asyncio.run(build_check(request, config))
    _print_json(result.to_dict())
    return EXIT_OK if result.ok else EXIT_VERIFY_FAILED


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.verb == "capabilities":
            config = load_platform_config(args.config) if args.config else None
            _print_json(_capabilities(config))
            return EXIT_OK
        if args.verb == "doctor":
            config = load_platform_config(args.config)
            result = run_doctor(config)
            _print_json(result)
            return EXIT_OK if result["ok"] else EXIT_VERIFY_FAILED
        if args.verb == "build-check":
            return _run_build(args)
        if args.verb == "apply-plan":
            # Refuse even before reading config or inputs: commit is not a Platform capability.
            if args.commit:
                from .orchestrator import APPLY_COMMIT_GATE
                raise BuildCheckError("commit_refused", "native commit is disabled at gate " + APPLY_COMMIT_GATE,
                                      {"gate": APPLY_COMMIT_GATE})
            result = asyncio.run(design_apply_plan(
                manifest_path=args.manifest_path, project=args.project, output_dir=args.output_dir,
                config=load_platform_config(args.config), expected_revision=args.expected_revision,
            ))
            _print_json(result)
            return EXIT_OK if result["status"] == "planned" else EXIT_VERIFY_FAILED
        if args.verb == "manifest" and args.manifest_verb == "verify":
            result = verify_manifest(args.path, verify_files=not args.no_file_check)
            _print_json(result.to_dict())
            return EXIT_OK if result.valid else EXIT_MANIFEST_INVALID
        if args.verb == "open":
            result = open_view(
                manifest_path=str(args.manifest.expanduser().absolute()),
                target_view=args.target_view,
                expected_manifest_sha256=args.expected_manifest_sha256,
                source_view=args.source_view,
                focus=not args.no_focus,
                dry_run=args.dry_run,
            )
            _print_json(result)
            return EXIT_OK
        if args.verb == "open-uri":
            _print_json(open_uri(args.uri, dry_run=args.dry_run))
            return EXIT_OK
        parser.error("unknown command")
    except (BuildCheckError, LaunchError) as exc:
        _print_json({"error": exc.to_dict()}, stream=sys.stderr)
        return EXIT_VERIFY_FAILED
    except (ManifestError, ValueError, OSError) as exc:
        _print_json({"error": {"code": "invalid_request", "message": str(exc)}}, stream=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        _print_json({"error": {"code": "cancelled", "message": "operation cancelled"}}, stream=sys.stderr)
        return 130
    return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
