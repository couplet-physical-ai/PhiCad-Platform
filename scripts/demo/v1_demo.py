#!/usr/bin/env python3
"""Reproducible PhiCad V1 demo and media-capture harness.

The harness deliberately treats a captured run and a design verdict as different things.  It
copies the TSX input into a new run directory, runs the configured Circuit Engine, records the
combined Build/PhiCad Verify result, and writes every command's byte-for-byte stdout/stderr plus
metadata and SHA-256 hashes.  A missing real tool is an evidence-producing blocker, not a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXAMPLE = ROOT / "examples" / "demo-v1-led.tsx"
MANIFEST_FIXTURE = ROOT / "examples" / "fixtures" / "demo-v1-led.expected-manifest.json"
DIAGNOSTICS_FIXTURE = ROOT / "examples" / "fixtures" / "demo-v1-led.expected-diagnostics.json"
SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "TERM",
    "USER",
    "SHELL",
    "PHICAD_BUILD",
    "PHICAD_KICAD_CLI",
    "KICAD_RUN_FROM_BUILD_DIR",
)


class HarnessError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def child_environment() -> dict[str, str]:
    """Use the small, non-secret environment needed by local tools.

    In particular, proxy variables and arbitrary *_TOKEN/*_KEY values are not copied into a
    Circuit Engine or verifier process.  PHICAD_KICAD_CLI and PHICAD_BUILD are explicit tool
    selectors, not credentials, and are retained so PhiCad Verify can find its configured CLI.
    """
    env = {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}
    for key in ("PHICAD_KICAD_CLI", "PHICAD_BUILD"):
        if key not in env:
            continue
        candidate = Path(env[key]).expanduser()
        if not candidate.is_absolute() and candidate.exists():
            env[key] = str(candidate.resolve())
    env.update({"CI": "1", "NO_COLOR": "1"})
    return env


def command_text(argv: Sequence[str]) -> str:
    return shlex.join([str(item) for item in argv])


def parse_command(value: str, label: str) -> list[str]:
    try:
        argv = shlex.split(value)
    except ValueError as exc:
        raise HarnessError(f"invalid {label}: {exc}") from exc
    if not argv:
        raise HarnessError(f"{label} is empty")
    # The child runs from its fresh run directory so generated Circuit JSON cannot pollute the
    # checkout. Resolve explicit local script paths before changing cwd; bare names such as
    # `bun` and `phicad-core` remain PATH lookups.
    resolved = []
    for token in argv:
        candidate = Path(token).expanduser()
        if not candidate.is_absolute() and ("/" in token or token.startswith(".")) and candidate.is_file():
            resolved.append(str(candidate.resolve()))
        else:
            resolved.append(token)
    return resolved


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def parse_json_output(data: bytes) -> tuple[Any | None, str | None]:
    text = strip_ansi(data.decode("utf-8", errors="replace")).strip()
    if not text:
        return None, "stdout was empty"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as first_error:
        # A CLI may print a progress line before its JSON result.  Keep the original bytes in the
        # command capture and only make the structured result tolerant of that harmless prefix.
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                return decoder.raw_decode(text[index:])[0], None
            except json.JSONDecodeError:
                continue
        return None, f"stdout was not JSON: {first_error.msg}"


def finding_codes(payload: Any, key: str = "findings") -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        return []
    return [item["code"] for item in payload[key] if isinstance(item, dict) and isinstance(item.get("code"), str)]


def finding_count(payload: Any, severity: str, key: str = "findings") -> int:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        return 0
    return sum(
        1
        for item in payload[key]
        if isinstance(item, dict) and str(item.get("severity", "")).lower() == severity
    )


def make_run_dir(requested: str | None) -> Path:
    if requested:
        path = Path(requested).expanduser().resolve()
        if path.exists():
            raise HarnessError(f"run directory already exists; refusing to overwrite: {path}")
        path.mkdir(parents=True)
    else:
        path = Path(tempfile.mkdtemp(prefix="phicad-v1-demo-"))
    (path / "inputs").mkdir()
    (path / "commands").mkdir()
    (path / "outputs").mkdir()
    return path


class CommandRecorder:
    def __init__(self, run_dir: Path, timeout_seconds: float) -> None:
        self.run_dir = run_dir
        self.timeout_seconds = timeout_seconds
        self.records: list[dict[str, Any]] = []
        self.env = child_environment()

    def run(self, label: str, argv: Sequence[str], cwd: Path) -> dict[str, Any]:
        index = len(self.records) + 1
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label)
        stdout_path = self.run_dir / "commands" / f"{index:03d}-{safe_label}.stdout"
        stderr_path = self.run_dir / "commands" / f"{index:03d}-{safe_label}.stderr"
        started_at = utc_now()
        started = time.monotonic()
        returncode: int | None = None
        timed_out = False
        spawn_error: str | None = None
        stdout = b""
        stderr = b""
        try:
            completed = subprocess.run(
                [str(item) for item in argv],
                cwd=str(cwd),
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            if isinstance(stdout, str):
                stdout = stdout.encode("utf-8", errors="replace")
            if isinstance(stderr, str):
                stderr = stderr.encode("utf-8", errors="replace")
            stderr += f"\n[harness] timed out after {self.timeout_seconds:g}s\n".encode()
        except OSError as exc:
            spawn_error = f"{type(exc).__name__}: {exc}"
            stderr = f"[harness] {spawn_error}\n".encode()

        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        record: dict[str, Any] = {
            "id": f"cmd-{index:03d}",
            "label": label,
            "argv": [str(item) for item in argv],
            "command": command_text(argv),
            "cwd": str(cwd),
            "environment": dict(sorted(self.env.items())),
            "started_at": started_at,
            "duration_ms": duration_ms,
            "returncode": returncode,
            "timed_out": timed_out,
            "spawn_error": spawn_error,
            "stdout_file": stdout_path.relative_to(self.run_dir).as_posix(),
            "stderr_file": stderr_path.relative_to(self.run_dir).as_posix(),
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_sha256": sha256_bytes(stdout),
            "stderr_sha256": sha256_bytes(stderr),
        }
        self.records.append(record)
        return {**record, "stdout": stdout, "stderr": stderr}

    def write_jsonl(self) -> None:
        path = self.run_dir / "commands.jsonl"
        with path.open("w", encoding="utf-8") as stream:
            for record in self.records:
                stream.write(json.dumps(record, sort_keys=True) + "\n")


def resolve_engine_command(explicit: str | None) -> tuple[list[str], str]:
    value = explicit or os.environ.get("PHICAD_ENGINE_CMD")
    if value:
        return parse_command(value, "engine command"), "explicit"

    cli = os.environ.get("PHICAD_CORE_CLI")
    if not cli:
        repo = os.environ.get("PHICAD_REPO")
        if repo and (Path(repo) / "core" / "cli.mjs").is_file():
            cli = str(Path(repo) / "core" / "cli.mjs")
    if cli:
        cli_path = Path(cli).expanduser()
        if not cli_path.is_absolute() and cli_path.is_file():
            cli = str(cli_path.resolve())
        bun = os.environ.get("PHICAD_BUN") or shutil.which("bun") or "bun"
        return [bun, cli], "PHICAD_CORE_CLI/PHICAD_REPO"

    installed = shutil.which("phicad-core") or shutil.which("phicad")
    if installed:
        return [installed], "PATH"
    # Keep the missing binary as the command.  This produces a recorded, actionable blocker
    # instead of silently selecting an unpinned package or declaring a skipped pass.
    return ["phicad-core"], "default-missing-command"


def package_metadata(argv: Sequence[str]) -> dict[str, Any] | None:
    for token in argv:
        path = Path(token)
        if path.name != "cli.mjs":
            continue
        package_path = path.parent / "package.json"
        if not package_path.is_file():
            continue
        try:
            raw = package_path.read_bytes()
            package = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue
        return {
            "path": str(package_path),
            "sha256": sha256_bytes(raw),
            "name": package.get("name"),
            "version": package.get("version"),
            "dependencies": package.get("dependencies", {}),
        }
    return None


def set_output_text(result: dict[str, Any]) -> dict[str, Any]:
    result["stdout_text"] = result["stdout"].decode("utf-8", errors="replace")
    result["stderr_text"] = result["stderr"].decode("utf-8", errors="replace")
    return result


def reported_version(version_record: dict[str, Any]) -> str | None:
    if version_record.get("returncode") != 0:
        return None
    text = (version_record.get("stdout_text") or version_record.get("stderr_text") or "").strip()
    return text.splitlines()[0] if text else None


def record_payload(path: Path, result: dict[str, Any]) -> tuple[Any | None, str | None]:
    payload, parse_error = parse_json_output(result["stdout"])
    if payload is not None:
        json_write(path, payload)
    else:
        json_write(path, {
            "parse_ok": False,
            "parse_error": parse_error,
            "stdout_sha256": result["stdout_sha256"],
            "stdout_file": result["stdout_file"],
            "returncode": result["returncode"],
        })
    return payload, parse_error


def summarize_check(result: dict[str, Any], payload: Any | None) -> dict[str, Any]:
    return {
        "command_id": result["id"],
        "exit_code": result["returncode"],
        "timed_out": result["timed_out"],
        "ok": payload.get("ok") if isinstance(payload, dict) else None,
        "finding_codes": finding_codes(payload),
    }


def summarize_build(result: dict[str, Any], payload: Any | None) -> dict[str, Any]:
    engine = payload.get("engine") if isinstance(payload, dict) else {}
    verification = payload.get("verification") if isinstance(payload, dict) else {}
    if not isinstance(engine, dict):
        engine = {}
    if not isinstance(verification, dict):
        verification = {}
    return {
        "command_id": result["id"],
        "exit_code": result["returncode"],
        "timed_out": result["timed_out"],
        "ok": payload.get("ok") if isinstance(payload, dict) else None,
        "engine_ok": engine.get("ok"),
        "engine_errors": finding_count(engine, "error"),
        "engine_warnings": finding_count(engine, "warning"),
        "engine_finding_codes": finding_codes(engine),
        "verification_ok": verification.get("ok"),
        "verification_skipped": verification.get("skipped"),
        "verification_errors": finding_count(verification, "error"),
        "verification_warnings": finding_count(verification, "warning"),
        "verification_finding_codes": finding_codes(verification),
    }


def compare_expected(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        checks[key] = {"expected": expected_value, "actual": actual_value, "match": actual_value == expected_value}
    return {
        "match": all(item["match"] for item in checks.values()),
        "checks": checks,
    }


def all_files(run_dir: Path) -> Iterable[Path]:
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            yield path


def make_manifest(run_dir: Path) -> dict[str, Any]:
    entries = []
    for path in all_files(run_dir):
        relative = path.relative_to(run_dir).as_posix()
        if relative.startswith("inputs/"):
            role = "input"
        elif relative.startswith("commands/"):
            role = "command-output"
        elif relative.startswith("outputs/"):
            role = "structured-output"
        else:
            role = "run-metadata"
        entries.append({
            "path": relative,
            "role": role,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return {
        "schema_version": 2,
        "algorithm": "sha256",
        "example": "examples/demo-v1-led.tsx",
        "fabrication_ready": False,
        "phicad_native_materialization": "unavailable-v1",
        "files": entries,
    }


def print_summary(run_dir: Path, diagnostics: dict[str, Any]) -> None:
    check = diagnostics["observed"]["engine_check"]
    build = diagnostics["observed"]["build_and_verify"]

    def verdict(item: dict[str, Any]) -> str:
        if item["exit_code"] is None:
            return "UNAVAILABLE"
        if item.get("ok") is True:
            return "PASS"
        if item.get("ok") is False:
            return "FAIL"
        return "UNPARSED"

    print("PHICAD / V1 SMALL-BOARD DEMO")
    print(f"run directory: {run_dir}")
    print(f"engine check: {verdict(check)} (exit={check['exit_code']})")
    print(f"build + PhiCad Verify: {verdict(build)} (exit={build['exit_code']})")
    print(f"fixture: {'MATCH' if diagnostics['fixture_match']['match'] else 'MISMATCH'}")
    print("fabrication status: NOT CLAIMED")
    print("PhiCad native materialization: UNAVAILABLE IN V1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", help="new output directory; existing directories are rejected")
    parser.add_argument("--example", default=str(DEFAULT_EXAMPLE), help="TSX input (default: the V1 LED example)")
    parser.add_argument("--engine-command", help="quoted command vector, e.g. '/path/to/bun /path/to/core/cli.mjs'")
    parser.add_argument("--timeout", type=float, default=300.0, help="per-command timeout in seconds (default: 300)")
    parser.add_argument("--strict", action="store_true", help="return 1 when a tool command or design verdict fails")
    parser.add_argument("--quiet", action="store_true", help="do not print the stable terminal summary")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started_at = utc_now()
    started = time.monotonic()
    try:
        example = Path(args.example).expanduser().resolve()
        if not example.is_file():
            raise HarnessError(f"example does not exist: {example}")
        run_dir = make_run_dir(args.run_dir)
        input_path = run_dir / "inputs" / example.name
        shutil.copyfile(example, input_path)
        fixture_input_dir = run_dir / "inputs" / "fixtures"
        fixture_input_dir.mkdir()
        shutil.copyfile(MANIFEST_FIXTURE, fixture_input_dir / MANIFEST_FIXTURE.name)
        shutil.copyfile(DIAGNOSTICS_FIXTURE, fixture_input_dir / DIAGNOSTICS_FIXTURE.name)
        engine, engine_resolution = resolve_engine_command(args.engine_command)
        recorder = CommandRecorder(run_dir, args.timeout)

        # Record the launcher separately when the engine is a script behind Bun/Node/Python.  The
        # package manifest below pins the engine/dependencies, while this records the executable
        # that actually interpreted it.  A bare installed phicad-core has its own version probe.
        launcher_result: dict[str, Any] | None = None
        if len(engine) > 1:
            launcher_result = set_output_text(recorder.run("launcher-version", [engine[0], "--version"], run_dir))
        version_result = set_output_text(recorder.run("engine-version", [*engine, "--version"], run_dir))
        check_result = recorder.run("engine-check", [*engine, "check", f"inputs/{example.name}", "--json"], run_dir)
        check_payload, check_parse_error = record_payload(run_dir / "outputs" / "engine-check.json", check_result)
        build_result = recorder.run("build-and-verify", [*engine, "build", f"inputs/{example.name}", "--json"], run_dir)
        build_payload, build_parse_error = record_payload(run_dir / "outputs" / "build-verify.json", build_result)

        verifier_version: dict[str, Any] | None = None
        verifier = os.environ.get("PHICAD_KICAD_CLI")
        if verifier:
            verifier_path = Path(verifier).expanduser()
            if not verifier_path.is_absolute() and verifier_path.is_file():
                verifier = str(verifier_path.resolve())
            verifier_version = set_output_text(recorder.run("verifier-version", [verifier, "--version"], run_dir))

        check_actual = summarize_check(check_result, check_payload)
        build_actual = summarize_build(build_result, build_payload)
        fixture = json.loads(DIAGNOSTICS_FIXTURE.read_text(encoding="utf-8"))
        manifest_contract = json.loads(MANIFEST_FIXTURE.read_text(encoding="utf-8"))
        fixture_expected = fixture["expected"]
        build_fixture_key = "build_and_verify_with_pinned_kicad" if verifier else "build_and_verify"
        fixture_match = {
            "match": (
                compare_expected(check_actual, fixture_expected["engine_check"])["match"]
                and compare_expected(build_actual, fixture_expected[build_fixture_key])["match"]
            ),
            "engine_check": compare_expected(check_actual, fixture_expected["engine_check"]),
            "build_and_verify": compare_expected(build_actual, fixture_expected[build_fixture_key]),
            "build_fixture_key": build_fixture_key,
        }
        diagnostics = {
            "schema_version": 2,
            "example": "examples/demo-v1-led.tsx",
            "observed": {
                "engine_check": check_actual,
                "build_and_verify": build_actual,
                "parse_errors": {
                    "engine_check": check_parse_error,
                    "build_and_verify": build_parse_error,
                },
            },
            "fixture": {
                "path": "examples/fixtures/demo-v1-led.expected-diagnostics.json",
                "status": fixture["fixture_status"],
            },
            "fixture_match": fixture_match,
            "manifest_contract": {
                "path": "examples/fixtures/demo-v1-led.expected-manifest.json",
                "schema_version": manifest_contract["schema_version"],
                "required_paths": manifest_contract["required_paths"],
                "required_command_labels": manifest_contract["required_command_labels"],
            },
            "known_findings": fixture["known_findings"],
            "claims_not_made": fixture["claims_not_made"],
            "fabrication_ready": False,
            "phicad_native_materialization": {
                "status": "unavailable-v1",
                "statement": "V1 verifies exact Circuit JSON bytes but does not materialize them into a native PhiCad revision.",
            },
        }
        json_write(run_dir / "diagnostics.json", diagnostics)
        recorder.write_jsonl()

        package = package_metadata(engine)
        tool_versions: dict[str, Any] = {
            "schema_version": 1,
            "harness": {
                "python": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "script": str(Path(__file__).resolve()),
            },
            "launcher": {
                "command": [engine[0]],
                "version_command_id": launcher_result["id"] if launcher_result else None,
                "reported_version": reported_version(launcher_result) if launcher_result else None,
                "version_exit_code": launcher_result["returncode"] if launcher_result else None,
            },
            "engine": {
                "command": engine,
                "resolution": engine_resolution,
                "version_command_id": version_result["id"],
                "reported_version": reported_version(version_result),
                "version_exit_code": version_result["returncode"],
                "package": package,
            },
            "verifier": {
                "configured_cli": verifier,
                "version_command_id": verifier_version["id"] if verifier_version else None,
                "reported_version": reported_version(verifier_version) if verifier_version else None,
                "version_exit_code": verifier_version["returncode"] if verifier_version else None,
            },
            "dependency_policy": "The harness does not install or resolve packages at run time; use the pinned tool supplied by the caller.",
        }
        json_write(run_dir / "tool-versions.json", tool_versions)

        duration_ms = round((time.monotonic() - started) * 1000, 3)
        run_metadata = {
            "schema_version": 1,
            "run_id": run_dir.name,
            "started_at": started_at,
            "finished_at": utc_now(),
            "duration_ms": duration_ms,
            "example_source": str(example),
            "input_snapshot": "inputs/" + example.name,
            "engine_resolution": engine_resolution,
            "strict": args.strict,
            "capture_status": "complete",
            "design_verdict_is_not_fabrication_verdict": True,
        }
        json_write(run_dir / "run.json", run_metadata)
        manifest = make_manifest(run_dir)
        present_paths = {entry["path"] for entry in manifest["files"]}
        # manifest.json is intentionally excluded from its own hash list to avoid a recursive
        # checksum, but it is still a required output path in the contract.
        present_paths.add("manifest.json")
        recorded_labels = {record["label"] for record in recorder.records}
        manifest["fixture_contract"] = {
            "path": "examples/fixtures/demo-v1-led.expected-manifest.json",
            "match": (
                set(manifest_contract["required_paths"]).issubset(present_paths)
                and set(manifest_contract["required_command_labels"]).issubset(recorded_labels)
            ),
        }
        json_write(run_dir / "manifest.json", manifest)

        if not args.quiet:
            print_summary(run_dir, diagnostics)
        if args.strict:
            required_labels = {"engine-check", "build-and-verify"}
            if verifier:
                required_labels.add("verifier-version")
            commands_ok = all(
                record["returncode"] == 0
                for record in recorder.records
                if record["label"] in required_labels
            )
            verdicts_ok = check_actual["ok"] is True and build_actual["ok"] is True
            return 0 if commands_ok and verdicts_ok and fixture_match["match"] else 1
        return 0
    except HarnessError as exc:
        print(f"demo harness error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # keep an unexpected harness defect distinguishable from a tool failure
        print(f"demo harness internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
