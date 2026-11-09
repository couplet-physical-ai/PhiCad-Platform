"""Deterministic Verify orchestration with bounded, cancellable subprocesses."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .contracts import (
    DIAGNOSTIC_ORIGINS,
    ArtifactRecord,
    BuildCheckRequest,
    DiagnosticCounts,
    PlatformConfig,
    VerifyCliConfig,
    VerifyLimits,
)
from .manifest import (
    MANIFEST_SCHEMA_VERSION,
    ManifestError,
    NativeApply,
    create_manifest,
    load_manifest,
    native_tool_versions,
    sha256_bytes,
    sha256_file,
    sha256_path,
    write_manifest,
)


class BuildCheckError(RuntimeError):
    """An expected, user-actionable build-check failure."""

    def __init__(self, code: str, message: str, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "details": self.details, "message": self.message}


def _reject_non_json_constant(value: str) -> None:
    raise ValueError("non-standard JSON constant: %s" % value)


class _OutputLimitExceeded(Exception):
    def __init__(self, stream: str, limit: int) -> None:
        self.stream = stream
        self.limit = limit
        super().__init__("%s exceeded %d bytes" % (stream, limit))


@dataclass(frozen=True)
class BuildCheckResult:
    ok: bool
    returncode: int
    command: Tuple[str, ...]
    output_dir: str
    manifest_path: str
    stdout: str
    stderr: str
    manifest: Any

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "command": list(self.command),
            "manifest": self.manifest.to_dict(),
            "manifest_path": self.manifest_path,
            "ok": self.ok,
            "output_dir": self.output_dir,
            "returncode": self.returncode,
            "stderr": self.stderr,
            "stdout": self.stdout,
        }
        return result


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_versions_lock(project_dir: Optional[Path] = None) -> Path:
    project_dir = Path(project_dir or Path.cwd()).resolve()
    candidates = [project_dir / "versions.lock.json", _package_root() / "versions.lock.json"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def _candidate_verify_executables(project_dir: Optional[Path] = None) -> Iterable[Path]:
    """Look only in conventional sibling developer checkouts, never download."""
    project_dir = Path(project_dir or Path.cwd()).resolve()
    parent = project_dir.parent
    checkout_names = (
        "PhiCad-Verify",
        "phicad-verify",
        "PhiCadVerify",
        "phicad_verify",
        "PhiCad-Platform-Verify",
    )
    binary_names = ("phicad-verify", "phicad_verify", "phicad-verify-cli")
    for checkout_name in checkout_names:
        checkout = parent / checkout_name
        for relative in (Path("bin"), Path("dist"), Path("build"), Path("")):
            for binary_name in binary_names:
                yield checkout / relative / binary_name


def discover_verify_command(project_dir: Optional[Path] = None) -> Optional[Tuple[str, ...]]:
    """Return an absolute installed or sibling-checkout Verify command."""
    for candidate in _candidate_verify_executables(project_dir):
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return (str(candidate.resolve()),)
    # A developer checkout exposes the same service contract through its
    # pinned Bun CLI.  Resolve Bun now; never use bunx or a dynamic download.
    bun = shutil.which("bun")
    if bun:
        project_dir = Path(project_dir or Path.cwd()).resolve()
        parents = (project_dir.parent, _package_root().parent)
        for parent in parents:
            core_cli = parent / "PhiCad" / "phicad" / "core" / "cli.mjs"
            if core_cli.is_file():
                return (str(Path(bun).resolve()), str(core_cli.resolve()))
    # PATH lookup is a convenience only.  The resolved path is written into
    # the manifest, so the invocation is still explicit after discovery.
    path_candidate = shutil.which("phicad-verify") or shutil.which("phicad_verify")
    if path_candidate:
        return (str(Path(path_candidate).resolve()),)
    return None


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildCheckError("invalid_config", "cannot read JSON file %s: %s" % (path, exc))
    if not isinstance(value, Mapping):
        raise BuildCheckError("invalid_config", "JSON root must be an object: %s" % path)
    return value


def _version_map(lock: Mapping[str, Any]) -> Dict[str, str]:
    raw_tools = lock.get("tools", {})
    if not isinstance(raw_tools, Mapping):
        raise BuildCheckError("invalid_versions_lock", "versions lock tools must be an object")
    result: Dict[str, str] = {}
    for name, value in raw_tools.items():
        if isinstance(value, Mapping):
            version = value.get("version")
        else:
            version = value
        if not isinstance(name, str) or not isinstance(version, str) or not version.strip():
            raise BuildCheckError("invalid_versions_lock", "tool versions must be exact strings")
        result[name] = version
    if not result:
        raise BuildCheckError("invalid_versions_lock", "versions lock has no tools")
    return result


def _limits_from_mapping(value: Mapping[str, Any]) -> VerifyLimits:
    defaults = VerifyLimits()
    kwargs: Dict[str, Any] = {}
    for name, default in (
        ("timeout_seconds", defaults.timeout_seconds),
        ("max_source_bytes", defaults.max_source_bytes),
        ("max_circuit_json_bytes", defaults.max_circuit_json_bytes),
        ("max_circuit_json_elements", defaults.max_circuit_json_elements),
        ("max_stdout_bytes", defaults.max_stdout_bytes),
        ("max_stderr_bytes", defaults.max_stderr_bytes),
        ("max_result_bytes", defaults.max_result_bytes),
        ("max_output_files", defaults.max_output_files),
        ("max_output_bytes", defaults.max_output_bytes),
        ("terminate_grace_seconds", defaults.terminate_grace_seconds),
    ):
        kwargs[name] = value.get(name, default)
    try:
        return VerifyLimits(**kwargs)
    except (TypeError, ValueError) as exc:
        raise BuildCheckError("invalid_config", "invalid verifier limits: %s" % exc)


def _make_verify_config(
    raw: Optional[Mapping[str, Any]],
    project_dir: Path,
) -> VerifyCliConfig:
    raw = dict(raw or {})
    command_value = raw.get("command")
    command_is_exact = command_value is not None
    if command_value is None:
        command_value = raw.get("verify_command")
        command_is_exact = command_value is not None
    if command_value is None:
        command_value = raw.get("executable") or raw.get("path")
    if command_value is None:
        discovered = discover_verify_command(project_dir)
        command_value = discovered or ("phicad-verify",)
    if isinstance(command_value, str):
        command = (command_value,)
    elif isinstance(command_value, (list, tuple)):
        command = tuple(str(part) for part in command_value)
    else:
        raise BuildCheckError("invalid_config", "verify command must be a string or argv array")
    # A bare executable is a convenience form.  A command/verify_command is
    # already exact and is never augmented or reordered.
    if not command_is_exact and not any("{output_dir}" in part for part in command):
        command = command + (
            "verify",
            "--circuit-json",
            "{circuit_json}",
            "--output-dir",
            "{output_dir}",
            "--result",
            "{result}",
        )

    limits_raw = raw.get("limits", {})
    if not isinstance(limits_raw, Mapping):
        raise BuildCheckError("invalid_config", "verify limits must be an object")
    # Accept limits at either level for a compact developer config.
    merged_limits = dict(limits_raw)
    limit_names = (
        "timeout_seconds",
        "max_source_bytes",
        "max_circuit_json_bytes",
        "max_circuit_json_elements",
        "max_stdout_bytes",
        "max_stderr_bytes",
        "max_result_bytes",
        "max_output_files",
        "max_output_bytes",
        "terminate_grace_seconds",
    )
    for key in limit_names:
        if key in raw:
            merged_limits[key] = raw[key]
    allowlist = raw.get("env_allowlist", VerifyCliConfig(command=command).env_allowlist)
    if not isinstance(allowlist, (list, tuple)):
        raise BuildCheckError("invalid_config", "env_allowlist must be an array")
    environment = raw.get("environment", {})
    if not isinstance(environment, Mapping):
        raise BuildCheckError("invalid_config", "environment must be an object")
    try:
        return VerifyCliConfig(
            command=command,
            result_file=str(raw.get("result_file", "verify-result.json")),
            limits=_limits_from_mapping(merged_limits),
            env_allowlist=tuple(str(item) for item in allowlist),
            environment={str(key): str(value) for key, value in environment.items()},
        )
    except (TypeError, ValueError) as exc:
        raise BuildCheckError("invalid_config", str(exc))


def load_platform_config(
    config_path: Optional[Path] = None,
    project_dir: Optional[Path] = None,
) -> PlatformConfig:
    project_dir = Path(project_dir or Path.cwd()).resolve()
    explicit_path = Path(config_path).resolve() if config_path else None
    raw: Mapping[str, Any] = {}
    selected_config: Optional[Path] = explicit_path
    if selected_config is None:
        default_config = project_dir / "phicad-platform.json"
        if default_config.is_file():
            selected_config = default_config.resolve()
    if selected_config:
        raw = _read_json(selected_config)

    lock_path_value = raw.get("versions_lock") or raw.get("versions_lock_path")
    lock_path = Path(lock_path_value).expanduser() if lock_path_value else _default_versions_lock(project_dir)
    if not lock_path.is_absolute():
        lock_path = (selected_config.parent if selected_config else project_dir) / lock_path
    lock_path = lock_path.resolve()
    if not lock_path.is_file():
        raise BuildCheckError("missing_versions_lock", "versions lock does not exist: %s" % lock_path)
    versions = _version_map(_read_json(lock_path))

    verify_raw = raw.get("verify_cli", {})
    if isinstance(verify_raw, str):
        verify_raw = {"command": verify_raw}
    if not isinstance(verify_raw, Mapping):
        raise BuildCheckError("invalid_config", "verify_cli must be an object or command string")
    if "verify_command" in raw and "command" not in verify_raw:
        verify_raw = dict(verify_raw)
        verify_raw["command"] = raw["verify_command"]
    verify = _make_verify_config(verify_raw, project_dir)

    configured_versions = raw.get("tool_versions", {})
    if not isinstance(configured_versions, Mapping):
        raise BuildCheckError("invalid_config", "tool_versions must be an object")
    for name, version in configured_versions.items():
        if not isinstance(name, str) or not isinstance(version, str) or not version.strip():
            raise BuildCheckError("invalid_config", "configured tool versions must be exact strings")
        versions[name] = version
    apply_raw = raw.get("apply_cli", {})
    if not isinstance(apply_raw, Mapping) or set(apply_raw) - {"executable"}:
        raise BuildCheckError("invalid_config", "apply_cli accepts only an operator executable path")
    apply_executable = apply_raw.get("executable")
    if apply_executable is not None and (
        not isinstance(apply_executable, str) or not Path(apply_executable).is_absolute()
    ):
        raise BuildCheckError("invalid_config", "apply_cli.executable must be an absolute path")
    return PlatformConfig(
        apply_executable=apply_executable,
        verify=verify,
        tool_versions=versions,
        versions_lock_path=str(lock_path),
        config_path=str(selected_config) if selected_config else None,
    )


def _resolve_executable(command: Sequence[str]) -> Tuple[str, ...]:
    if not command:
        raise BuildCheckError("missing_binary", "verify command is empty")
    executable = command[0]
    if os.path.isabs(executable):
        resolved = Path(executable)
        if not resolved.is_file() or not os.access(str(resolved), os.X_OK):
            raise BuildCheckError("missing_binary", "configured Verify executable is not executable: %s" % executable)
        return tuple(command)
    resolved_name = shutil.which(executable)
    if not resolved_name:
        raise BuildCheckError("missing_binary", "configured Verify executable was not found: %s" % executable)
    return (str(Path(resolved_name).resolve()),) + tuple(command[1:])


def _expand_command(
    command: Sequence[str],
    request: BuildCheckRequest,
    result_path: Path,
) -> Tuple[str, ...]:
    values = {
        "source": str(request.source.resolve()),
        "circuit_json": str(request.circuit_json.resolve()),
        "output_dir": str(request.output_dir.resolve()),
        "result": str(result_path.resolve()),
        "manifest": str(request.manifest_path.resolve()),
        "design_id": request.design_id,
        "studio": str(request.studio_path.resolve()) if request.studio_path else "",
    }
    expanded: List[str] = []
    for part in command:
        expanded_part = part
        for key, value in values.items():
            expanded_part = expanded_part.replace("{%s}" % key, value)
        expanded.append(expanded_part)
    return _resolve_executable(expanded)


def _prepare_output_dir(path: Path) -> None:
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise BuildCheckError("output_not_fresh", "output path is not a fresh directory: %s" % path)
        try:
            has_entries = next(path.iterdir(), None) is not None
        except OSError as exc:
            raise BuildCheckError("output_not_fresh", "cannot inspect output directory: %s" % exc)
        if has_entries:
            raise BuildCheckError(
                "output_not_fresh",
                "output directory must be empty; refusing to consume stale artifacts: %s" % path,
            )
    else:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise BuildCheckError("output_not_fresh", "cannot create output directory: %s" % exc)


def _require_bounded_regular_file(path: Path, label: str, max_bytes: int) -> None:
    if not path.is_file() or path.is_symlink():
        raise BuildCheckError("invalid_input", "%s must be a regular, non-symlink file: %s" % (label, path))
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BuildCheckError("invalid_input", "cannot inspect %s: %s" % (label, exc))
    if size > max_bytes:
        raise BuildCheckError(
            "input_limit",
            "%s exceeds its configured size limit" % label,
            {"actual_bytes": size, "limit_bytes": max_bytes},
        )


def _validate_circuit_json(path: Path, max_elements: int) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_non_json_constant)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise BuildCheckError("invalid_input", "Circuit JSON is not strict JSON: %s" % exc)
    if isinstance(value, list):
        elements = value
    elif isinstance(value, Mapping) and isinstance(value.get("elements"), list):
        elements = value["elements"]
    else:
        raise BuildCheckError("invalid_input", "Circuit JSON must be an element array or an object with an elements array")
    if len(elements) > max_elements:
        raise BuildCheckError(
            "input_limit",
            "Circuit JSON exceeds its configured element-count limit",
            {"actual_elements": len(elements), "limit_elements": max_elements},
        )


def _validate_output_tree(output_dir: Path, limits: VerifyLimits) -> None:
    files = 0
    total_bytes = 0
    try:
        candidates = sorted(output_dir.rglob("*"), key=lambda item: item.relative_to(output_dir).as_posix())
        for candidate in candidates:
            if candidate.is_symlink():
                raise BuildCheckError("unsafe_output", "Verify output contains a symlink: %s" % candidate)
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise BuildCheckError("unsafe_output", "Verify output is not a regular file: %s" % candidate)
            files += 1
            total_bytes += candidate.stat().st_size
            if files > limits.max_output_files:
                raise BuildCheckError(
                    "output_limit",
                    "Verify output exceeds its file-count limit",
                    {"actual_files": files, "limit_files": limits.max_output_files},
                )
            if total_bytes > limits.max_output_bytes:
                raise BuildCheckError(
                    "output_limit",
                    "Verify output exceeds its total-size limit",
                    {"actual_bytes": total_bytes, "limit_bytes": limits.max_output_bytes},
                )
    except BuildCheckError:
        raise
    except OSError as exc:
        raise BuildCheckError("unsafe_output", "cannot inspect Verify output: %s" % exc)


def _safe_child_environment(config: VerifyCliConfig) -> Dict[str, str]:
    # Only these names are copied.  In particular, no proxy, token, key,
    # credential, or arbitrary parent environment reaches the verifier.
    environment: Dict[str, str] = {}
    for name in config.env_allowlist:
        if name in os.environ:
            environment[name] = os.environ[name]
    for name, value in config.environment.items():
        if name not in config.env_allowlist:
            raise BuildCheckError(
                "invalid_config",
                "configured environment key is not in env_allowlist: %s" % name,
            )
        environment[name] = value
    return environment


async def _read_limited(stream: Any, name: str, limit: int) -> bytes:
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(min(64 * 1024, limit + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise _OutputLimitExceeded(name, limit)
        chunks.append(chunk)


def _close_process_pipes(process: Any) -> None:
    # Python 3.12 can leave Process.wait() pending after a bounded StreamReader
    # stops consuming a full pipe. Close only the stdout/stderr transports once
    # termination begins so EOF is delivered without retaining unbounded data.
    transport = getattr(process, "_transport", None)
    if transport is None:
        return
    get_pipe_transport = getattr(transport, "get_pipe_transport", None)
    if get_pipe_transport is None:
        return
    for descriptor in (1, 2):
        pipe_transport = get_pipe_transport(descriptor)
        if pipe_transport is not None:
            pipe_transport.close()


def _close_process_transport(process: Any) -> None:
    # asyncio.Process has no public close method.  Closing its transport after
    # the group is reaped prevents late pipe callbacks when asyncio.run closes
    # the event loop (notably on Python 3.9).
    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()


async def _terminate_process_group(process: Any, grace_seconds: float) -> None:
    # Signal the group even when the direct child already exited: a verifier
    # that leaked a descendant can otherwise keep stdout/stderr pipes open.
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    _close_process_pipes(process)
    deadline = asyncio.get_running_loop().time() + grace_seconds
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        if os.name != "posix":
            return
        # The leader may exit while a descendant ignores SIGTERM. Give that group
        # the same grace, then kill it rather than mistaking leader exit for cleanup.
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))
    except (asyncio.TimeoutError, ProcessLookupError):
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


async def _run_process(command: Sequence[str], config: VerifyCliConfig) -> Tuple[int, bytes, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_safe_child_environment(config),
            start_new_session=True,
        )
    except FileNotFoundError:
        raise BuildCheckError("missing_binary", "configured Verify executable was not found: %s" % command[0])
    except PermissionError as exc:
        raise BuildCheckError("missing_binary", "configured Verify executable cannot run: %s" % exc)
    except OSError as exc:
        raise BuildCheckError("process_start_failed", "cannot start Verify executable: %s" % exc)

    stdout_task = asyncio.create_task(_read_limited(process.stdout, "stdout", config.limits.max_stdout_bytes))
    stderr_task = asyncio.create_task(_read_limited(process.stderr, "stderr", config.limits.max_stderr_bytes))
    wait_task = asyncio.create_task(process.wait())
    tasks = (stdout_task, stderr_task, wait_task)
    # Shield the aggregate: wait_for otherwise cancels the pipe readers on a
    # timeout, leaving the subprocess transport alive while the event loop is
    # being closed.  We kill the process group first, then drain those readers.
    aggregate = asyncio.gather(*tasks)
    try:
        await asyncio.wait_for(asyncio.shield(aggregate), timeout=config.limits.timeout_seconds)
    except asyncio.TimeoutError:
        await _terminate_process_group(process, config.limits.terminate_grace_seconds)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(aggregate, return_exceptions=True)
        _close_process_transport(process)
        raise BuildCheckError(
            "timeout",
            "Verify exceeded its timeout and the process group was terminated",
            {"timeout_seconds": config.limits.timeout_seconds},
        )
    except asyncio.CancelledError:
        await _terminate_process_group(process, config.limits.terminate_grace_seconds)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(aggregate, return_exceptions=True)
        _close_process_transport(process)
        raise
    except _OutputLimitExceeded as exc:
        await _terminate_process_group(process, config.limits.terminate_grace_seconds)
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(aggregate, return_exceptions=True)
        _close_process_transport(process)
        raise BuildCheckError(
            "output_limit",
            "%s exceeded its configured output limit" % exc.stream,
            {"stream": exc.stream, "limit_bytes": exc.limit},
        )
    stdout = stdout_task.result()
    stderr = stderr_task.result()
    returncode = process.returncode
    _close_process_transport(process)
    return returncode, stdout, stderr


def _read_result(path: Path, limit: int, stdout_payload: bytes = b"") -> Mapping[str, Any]:
    try:
        if path.is_file():
            # Read at most limit+1 bytes rather than trusting a pre-read stat;
            # a verifier could still be writing the file between operations.
            with path.open("rb") as handle:
                payload = handle.read(limit + 1)
            if len(payload) > limit:
                raise BuildCheckError("result_limit", "Verify result exceeds its configured size limit")
        elif stdout_payload.strip():
            # A configured command may return its structured result on stdout
            # instead of using the result placeholder.  stdout was already
            # bounded independently; apply the stricter result limit here too.
            payload = stdout_payload[: limit + 1]
            if len(stdout_payload) > limit:
                raise BuildCheckError("result_limit", "Verify stdout result exceeds its configured size limit")
        else:
            raise BuildCheckError("missing_result", "Verify produced neither its result file nor a JSON stdout result")
        data = json.loads(payload.decode("utf-8"), parse_constant=_reject_non_json_constant)
    except BuildCheckError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise BuildCheckError("invalid_result", "cannot read Verify result: %s" % exc)
    if not isinstance(data, Mapping):
        raise BuildCheckError("invalid_result", "Verify result must be a JSON object")
    return data


def _canonical_origin(value: Any) -> str:
    if not isinstance(value, str):
        raise BuildCheckError("invalid_result", "diagnostic origin must be a string")
    normalized = value.strip().lower().replace("-", "").replace("_", "")
    aliases = {"tscircuit": "tscircuit", "kicad": "kicad", "phicad": "kicad"}
    if normalized not in aliases:
        raise BuildCheckError("invalid_result", "unknown diagnostic origin: %s" % value)
    return aliases[normalized]


def _diagnostics_from_result(result: Mapping[str, Any]) -> Dict[str, DiagnosticCounts]:
    counts: Dict[str, Dict[str, int]] = {
        origin: {"errors": 0, "warnings": 0, "info": 0}
        for origin in DIAGNOSTIC_ORIGINS
    }
    diagnostic_items = result.get("diagnostics")
    raw = diagnostic_items if isinstance(diagnostic_items, list) else result.get("diagnostic_counts", diagnostic_items or {})
    if raw is None:
        raw = {}
    if isinstance(raw, Mapping):
        for origin_value, value in raw.items():
            origin = _canonical_origin(origin_value)
            if isinstance(value, Mapping):
                parsed = DiagnosticCounts.from_mapping(value)
                counts[origin] = parsed.to_dict()
            elif isinstance(value, int) and not isinstance(value, bool):
                counts[origin]["errors"] = value
            else:
                raise BuildCheckError("invalid_result", "diagnostic counts must be objects")
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                raise BuildCheckError("invalid_result", "diagnostic entries must be objects")
            origin = _canonical_origin(item.get("origin"))
            severity = str(item.get("severity", "error")).lower()
            severity = {
                "error": "errors",
                "warning": "warnings",
                "warn": "warnings",
                "information": "info",
                "informational": "info",
            }.get(severity, severity)
            if severity not in ("errors", "warnings", "info"):
                raise BuildCheckError("invalid_result", "unknown diagnostic severity: %s" % severity)
            counts[origin][severity] += 1
    else:
        raise BuildCheckError("invalid_result", "diagnostics must be an object or array")
    return {origin: DiagnosticCounts.from_mapping(counts[origin]) for origin in DIAGNOSTIC_ORIGINS}


def _diagnostic_status_from_result(
    result: Mapping[str, Any],
    diagnostics: Mapping[str, DiagnosticCounts],
) -> Dict[str, str]:
    raw = result.get("diagnostic_status")
    if raw is not None:
        if not isinstance(raw, Mapping):
            raise BuildCheckError("invalid_result", "diagnostic_status must be an object")
        statuses = {str(origin): str(status) for origin, status in raw.items()}
        if set(statuses) != set(DIAGNOSTIC_ORIGINS):
            raise BuildCheckError("invalid_result", "diagnostic_status must name every origin")
        return statuses

    reported_origins = set()
    raw_findings = result.get("diagnostics")
    if isinstance(raw_findings, list):
        for finding in raw_findings:
            if isinstance(finding, Mapping) and finding.get("origin") is not None:
                reported_origins.add(_canonical_origin(finding.get("origin")))

    statuses: Dict[str, str] = {}
    verdict = result.get("verdict")
    verdict_origin = None
    verdict_ok = None
    if isinstance(verdict, Mapping) and verdict.get("origin") is not None:
        verdict_origin = _canonical_origin(verdict.get("origin"))
        verdict_ok = verdict.get("ok")
    for origin in DIAGNOSTIC_ORIGINS:
        if origin == verdict_origin and isinstance(verdict_ok, bool):
            statuses[origin] = "passed" if verdict_ok else "failed"
        elif origin == "tscircuit" and origin in reported_origins:
            statuses[origin] = "carried-input"
        elif origin in reported_origins or diagnostics[origin].total:
            statuses[origin] = "reported"
        else:
            statuses[origin] = "not-run"
    return statuses


def _artifact_specs(result: Mapping[str, Any]) -> List[Tuple[str, str, Optional[str]]]:
    raw = result.get("artifacts")
    specs: List[Tuple[str, str, Optional[str]]] = []
    if isinstance(raw, Mapping):
        for kind, value in raw.items():
            if isinstance(value, str):
                specs.append((str(kind), value, None))
            elif isinstance(value, Mapping):
                specs.append((str(kind), str(value.get("path", "")), value.get("sha256")))
            else:
                raise BuildCheckError("invalid_result", "artifact entries must be paths or objects")
    elif isinstance(raw, list):
        for value in raw:
            if isinstance(value, str):
                specs.append((_infer_artifact_kind(Path(value)), value, None))
                continue
            if not isinstance(value, Mapping):
                raise BuildCheckError("invalid_result", "artifact entries must be paths or objects")
            path = value.get("path") or value.get("file")
            kind = value.get("kind") or value.get("type")
            if not path or not kind:
                raise BuildCheckError("invalid_result", "artifact needs kind and path")
            specs.append((str(kind), str(path), value.get("sha256")))
    elif raw is not None:
        raise BuildCheckError("invalid_result", "artifacts must be an object or array")
    return specs


def _infer_artifact_kind(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".kicad_pcb"):
        return "kicad-pcb"
    if lower.endswith(".kicad_pro"):
        return "kicad-project"
    if lower.endswith(".kicad_sch"):
        return "kicad-schematic"
    if lower.endswith(".kicad_prl"):
        return "kicad-local-settings"
    if lower in {"drc.json", "kicad-drc.json"} or "drc" in lower:
        return "kicad-drc"
    return "phicad"


def _collect_artifacts(result: Mapping[str, Any], output_dir: Path, result_path: Path) -> Tuple[ArtifactRecord, ...]:
    declared_hashes = result.get("artifact_hashes", {})
    if declared_hashes is None:
        declared_hashes = {}
    if not isinstance(declared_hashes, Mapping):
        raise BuildCheckError("invalid_result", "artifact_hashes must be an object")
    for kind, value in declared_hashes.items():
        if not isinstance(kind, str) or not isinstance(value, str):
            raise BuildCheckError("invalid_result", "artifact_hashes must map kinds to strings")
    specs = _artifact_specs(result)
    if not specs:
        files = (path for path in output_dir.rglob("*") if path.is_file())
        for candidate in sorted(files, key=lambda p: p.relative_to(output_dir).as_posix()):
            if candidate.resolve() == result_path.resolve():
                continue
            specs.append((_infer_artifact_kind(candidate), candidate.relative_to(output_dir).as_posix(), None))
    if not specs:
        raise BuildCheckError("no_artifacts", "Verify produced no PhiCad or KiCad artifact")

    records: List[ArtifactRecord] = []
    seen_kinds = set()
    seen_paths = set()
    for kind, relative_path, expected in specs:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise BuildCheckError("invalid_result", "artifact path escapes output directory: %s" % relative_path)
        artifact_path = (output_dir / candidate).resolve()
        try:
            artifact_path.relative_to(output_dir.resolve())
        except ValueError:
            raise BuildCheckError("invalid_result", "artifact path escapes output directory: %s" % relative_path)
        if artifact_path == result_path.resolve() or not artifact_path.is_file() or artifact_path.is_symlink():
            raise BuildCheckError(
                "stale_artifact",
                "artifact is missing or is not a fresh regular file: %s" % relative_path,
            )
        actual = sha256_file(artifact_path)
        expected_hash = expected if expected is not None else declared_hashes.get(kind, declared_hashes.get(candidate.as_posix()))
        if expected_hash is not None and expected_hash != actual:
            raise BuildCheckError(
                "stale_artifact",
                "Verify artifact hash does not match fresh output: %s" % relative_path,
                {"expected": expected_hash, "actual": actual},
            )
        if kind in seen_kinds:
            raise BuildCheckError("invalid_result", "duplicate artifact kind: %s" % kind)
        seen_kinds.add(kind)
        seen_paths.add(candidate.as_posix())
        try:
            records.append(ArtifactRecord(kind=str(kind), path=candidate.as_posix(), sha256=actual))
        except ValueError as exc:
            raise BuildCheckError("invalid_result", str(exc))
    missing_declared = set(declared_hashes) - seen_kinds - seen_paths
    if missing_declared:
        raise BuildCheckError(
            "stale_artifact",
            "Verify declared artifact kinds were not produced: %s" % ", ".join(sorted(missing_declared)),
        )
    return tuple(records)


def _check_declared_hash(result: Mapping[str, Any], key: str, expected: str) -> None:
    declared = result.get(key)
    if declared is not None and declared != expected:
        raise BuildCheckError("stale_input", "%s from Verify does not match the supplied input" % key)


def _check_declared_studio(result: Mapping[str, Any], request: BuildCheckRequest, studio_hash: str) -> None:
    raw = result.get("studio")
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise BuildCheckError("invalid_result", "studio evidence must be an object")
    if raw.get("revision") is not None and raw.get("revision") != request.studio_revision:
        raise BuildCheckError("stale_input", "Studio revision from Verify does not match the supplied revision")
    if raw.get("sha256") is not None and raw.get("sha256") != studio_hash:
        raise BuildCheckError("stale_input", "Studio hash from Verify does not match the supplied Studio input")


def _tool_versions(config: PlatformConfig, result: Mapping[str, Any]) -> Dict[str, str]:
    expected = dict(config.tool_versions)
    reported = result.get("tool_versions", {})
    if reported is None:
        reported = {}
    if not isinstance(reported, Mapping):
        raise BuildCheckError("invalid_result", "tool_versions must be an object")
    aliases = {"kicad-cli": "kicad", "service-contract": "phicad-verify-contract"}
    for name, version in reported.items():
        if not isinstance(name, str) or not isinstance(version, (str, int, float)) or isinstance(version, bool):
            raise BuildCheckError("invalid_result", "tool_versions must contain scalar version strings")
        version = str(version)
        expected_name = aliases.get(name, name)
        if expected_name in expected and expected[expected_name] != version:
            raise BuildCheckError(
                "tool_version_mismatch",
                "Verify reported %s=%s, but the lock/config pins %s" % (name, version, expected[expected_name]),
            )
        expected[name] = version
    return native_tool_versions(expected)


async def build_check(request: BuildCheckRequest, config: PlatformConfig) -> BuildCheckResult:
    """Run the exact configured Verify command and write a signed-by-hash manifest."""
    _require_bounded_regular_file(
        request.source,
        "source",
        config.verify.limits.max_source_bytes,
    )
    _require_bounded_regular_file(
        request.circuit_json,
        "Circuit JSON",
        config.verify.limits.max_circuit_json_bytes,
    )
    _validate_circuit_json(request.circuit_json, config.verify.limits.max_circuit_json_elements)
    if request.studio_path is not None:
        _require_bounded_regular_file(
            request.studio_path,
            "Studio input",
            config.verify.limits.max_output_bytes,
        )

    source_hash = sha256_path(request.source)
    circuit_json_hash = sha256_path(request.circuit_json)
    measured_studio_hash = sha256_path(request.studio_path) if request.studio_path else None
    if request.studio_hash and measured_studio_hash and request.studio_hash != measured_studio_hash:
        raise BuildCheckError("stale_input", "supplied Studio hash does not match the Studio file")
    studio_hash = request.studio_hash or measured_studio_hash
    if studio_hash is None:  # guarded by BuildCheckRequest, defensive for custom callers
        raise BuildCheckError("missing_input", "Studio hash evidence is required")
    result_path = request.output_dir / config.verify.result_file
    _prepare_output_dir(request.output_dir)
    command = _expand_command(config.verify.command, request, result_path)

    returncode, stdout_bytes, stderr_bytes = await _run_process(command, config.verify)
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if returncode != 0:
        raise BuildCheckError(
            "verifier_failed",
            "Verify exited with status %d" % returncode,
            {"returncode": returncode, "stderr": stderr, "stdout": stdout},
        )

    _validate_output_tree(request.output_dir, config.verify.limits)
    result = _read_result(result_path, config.verify.limits.max_result_bytes, stdout_bytes)
    _check_declared_hash(result, "source_hash", source_hash)
    _check_declared_hash(result, "circuit_json_hash", circuit_json_hash)
    _check_declared_studio(result, request, studio_hash)
    artifacts = _collect_artifacts(result, request.output_dir, result_path)
    diagnostics = _diagnostics_from_result(result)
    diagnostic_status = _diagnostic_status_from_result(result, diagnostics)
    tool_versions = _tool_versions(config, result)
    manifest = create_manifest(
        design_id=request.design_id,
        source_hash=source_hash,
        circuit_json_hash=circuit_json_hash,
        studio_revision=request.studio_revision,
        studio_hash=studio_hash,
        artifacts=artifacts,
        tool_versions=tool_versions,
        diagnostics=diagnostics,
        diagnostic_status=diagnostic_status,
        approval_state=request.approval_state,
        source_path=str(request.source.resolve()),
        circuit_json_path=str(request.circuit_json.resolve()),
        studio_path=str(request.studio_path.resolve()) if request.studio_path else None,
        configuration={
            "artifact_root": str(request.output_dir.resolve()),
            "config_path": config.config_path,
            "environment_allowlist": list(config.verify.env_allowlist),
            "manifest_path": str(request.manifest_path.resolve()),
            "verify_command": list(command),
            "verify_limits": config.verify.limits.to_dict(),
            "verify_result_file": config.verify.result_file,
            "verify_result_source": "file" if result_path.is_file() else "stdout",
            "versions_lock_path": config.versions_lock_path,
            "native_artifact_hash_source": "argument" if request.studio_hash else "native_artifact_path",
        },
    )
    write_manifest(manifest, request.manifest_path)
    return BuildCheckResult(
        ok=not any(item.errors for item in diagnostics.values()),
        returncode=returncode,
        command=tuple(command),
        output_dir=str(request.output_dir.resolve()),
        manifest_path=str(request.manifest_path.resolve()),
        stdout=stdout,
        stderr=stderr,
        manifest=manifest,
    )


def doctor(config: PlatformConfig) -> Dict[str, Any]:
    """Return a deterministic, non-mutating installation/configuration report."""
    command = config.verify.command
    executable = command[0] if command else ""
    if not os.path.isabs(executable):
        resolved = shutil.which(executable)
    else:
        resolved = executable
    exists = bool(resolved and Path(resolved).is_file() and os.access(str(resolved), os.X_OK))
    return {
        "capabilities": ["doctor", "capabilities", "build-check", "manifest verify"],
        "config": {
            "config_path": config.config_path,
            "versions_lock_path": config.versions_lock_path,
        },
        "environment": {
            "allowlist": list(config.verify.env_allowlist),
            "inherited_secrets": False,
        },
        "ok": exists,
        "verify_cli": {
            "command": list(command),
            "executable": str(Path(resolved).resolve()) if resolved else None,
            "exists_and_executable": exists,
        },
        "versions": dict(sorted(config.tool_versions.items())),
    }


APPLY_PLAN_SCHEMA = "io.github.couplet-physical-ai.phicad.apply-plan/v1"
APPLY_COMMIT_GATE = "platform_native_apply_plan_only"


def _no_symlink_path(path: Path) -> Path:
    path = path.expanduser().absolute()
    for part in (path, *path.parents):
        if part.is_symlink() and not (str(part) in {"/tmp", "/var"} and str(part.resolve()) == "/private" + str(part)):
            raise BuildCheckError("invalid_input", "apply paths must not traverse symlinks")
    return path.resolve()


def _parse_apply_plan(path: Path, circuit_hash: str, project: Path, returncode: int) -> Mapping[str, Any]:
    """Consume the actual PhiCad PhiCad native apply protocol shape, not Verify's result protocol."""
    plan = _read_result(path, VerifyLimits().max_result_bytes)
    required = {"schema", "status", "circuit_json_hash", "project", "counts", "coverage",
                "operations", "rejections", "plan_hash", "tool_versions"}
    if set(plan) != required or plan["schema"] != APPLY_PLAN_SCHEMA:
        raise BuildCheckError("invalid_apply_plan", "unknown apply plan schema or fields")
    if plan["status"] not in ("planned", "rejected") or returncode != (0 if plan["status"] == "planned" else 3):
        raise BuildCheckError("invalid_apply_plan", "plan status and child exit code disagree")
    payload = dict(plan)
    payload["plan_hash"] = ""
    # PhiCad hashes pretty, key-sorted, UTF-8 JSON INCLUDING its final newline.
    digest = sha256_bytes((json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2,
                                     allow_nan=False) + "\n").encode("utf-8"))
    if plan["plan_hash"] != digest or plan["circuit_json_hash"] != circuit_hash:
        raise BuildCheckError("stale_apply_plan", "apply plan hash or Circuit JSON hash differs")
    base = plan["project"]
    if not isinstance(base, Mapping) or set(base) != {"path", "base_revision", "base_board_hash"}:
        raise BuildCheckError("invalid_apply_plan", "invalid plan project")
    if base["path"] != str(project):
        raise BuildCheckError("stale_apply_plan", "apply plan names a different project")
    board_hash = base["base_board_hash"]
    if board_hash is not None and (not isinstance(board_hash, str) or len(board_hash) != 64
                                   or any(c not in "0123456789abcdef" for c in board_hash)):
        raise BuildCheckError("invalid_apply_plan", "invalid base board hash")
    counts = plan["counts"]
    if not isinstance(counts, Mapping) or set(counts) != {"components", "pads", "nets", "traces", "vias", "zones"}:
        raise BuildCheckError("invalid_apply_plan", "invalid plan counts")
    if any(type(v) is not int or v < 0 for v in counts.values()):
        raise BuildCheckError("invalid_apply_plan", "invalid plan count value")
    coverage = plan["coverage"]
    if not isinstance(coverage, Mapping) or set(coverage) != {"supported", "rejected"}:
        raise BuildCheckError("invalid_apply_plan", "invalid plan coverage")
    if any(not isinstance(v, list) or any(not isinstance(t, str) for t in v) for v in coverage.values()):
        raise BuildCheckError("invalid_apply_plan", "invalid coverage elements")
    if not isinstance(plan["operations"], list):
        raise BuildCheckError("invalid_apply_plan", "invalid operations")
    for operation in plan["operations"]:
        if not isinstance(operation, Mapping):
            raise BuildCheckError("invalid_apply_plan", "invalid operation record")
        op = operation.get("op")
        if op == "create_footprint":
            valid = (set(operation) == {"op", "ref", "layer", "at_nm", "rotation_deg"}
                     and isinstance(operation["ref"], str) and bool(operation["ref"])
                     and operation["layer"] in ("F.Cu", "B.Cu")
                     and isinstance(operation["at_nm"], list) and len(operation["at_nm"]) == 2
                     and all(type(n) is int for n in operation["at_nm"])
                     and type(operation["rotation_deg"]) in (int, float))
        elif op == "create_net":
            valid = (set(operation) == {"op", "name", "pins"}
                     and isinstance(operation["name"], str) and bool(operation["name"])
                     and isinstance(operation["pins"], list)
                     and all(isinstance(pin, str) and pin for pin in operation["pins"]))
        elif op in ("ignore_element", "ignore_field"):
            valid = (set(operation) == {"op", "element", "reason"}
                     and all(isinstance(operation[k], str) and operation[k] for k in ("element", "reason")))
        else:
            valid = False
        if not valid:
            raise BuildCheckError("invalid_apply_plan", "invalid operation record")
    if not isinstance(plan["tool_versions"], Mapping) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in plan["tool_versions"].items()
    ):
        raise BuildCheckError("invalid_apply_plan", "invalid plan tool versions")
    try:
        NativeApply(status=plan["status"], plan_hash=plan["plan_hash"], plan_path=path.name,
                    base_revision=base["base_revision"], rejections=plan["rejections"])
    except ManifestError as exc:
        raise BuildCheckError("invalid_apply_plan", str(exc))
    if bool(plan["rejections"]) != (plan["status"] == "rejected"):
        raise BuildCheckError("invalid_apply_plan", "plan status contradicts its rejections")
    if plan["status"] == "planned" and coverage["rejected"]:
        raise BuildCheckError("invalid_apply_plan", "planned status has rejected coverage")
    return plan


async def design_apply_plan(
    *, manifest_path: Path, project: Path, output_dir: Path,
    config: PlatformConfig, expected_revision: Optional[str] = None, commit: bool = False,
) -> Dict[str, Any]:
    """Plan only: no caller command, no template expansion, and NEVER --commit.

    A fresh output holds plan.json and a new V3 manifest; neither the input manifest
    nor the native project is overwritten. Missing apply support is not a plan.
    """
    if commit is not False:
        raise BuildCheckError("commit_refused", "native commit is disabled at gate " + APPLY_COMMIT_GATE,
                              {"gate": APPLY_COMMIT_GATE})
    limits = VerifyLimits()  # operator config cannot relax the apply boundary
    manifest_path = _no_symlink_path(manifest_path)
    output_dir = _no_symlink_path(output_dir)
    project = _no_symlink_path(project)
    _require_bounded_regular_file(manifest_path, "manifest", limits.max_result_bytes)
    manifest = load_manifest(manifest_path)
    project_root = project.parent if project.suffix == ".kicad_pro" else project
    if output_dir == project_root or project_root in output_dir.parents:
        raise BuildCheckError("unsafe_output", "apply evidence must be outside the native project")
    if output_dir == manifest_path.parent or output_dir in manifest_path.parents:
        raise BuildCheckError("unsafe_output", "apply evidence must not contain the input manifest")
    if not manifest.circuit_json_path:
        raise BuildCheckError("invalid_input", "manifest has no Circuit JSON path")
    circuit = Path(manifest.circuit_json_path)
    if not circuit.is_absolute():
        circuit = manifest_path.parent / circuit
    circuit = _no_symlink_path(circuit)
    # PhiCad native apply protocol currently imposes a stricter 2 MiB Circuit JSON cap than section 7's 32 MiB.
    _require_bounded_regular_file(circuit, "Circuit JSON", limits.max_source_bytes)
    _validate_circuit_json(circuit, limits.max_circuit_json_elements)
    if not isinstance(json.loads(circuit.read_text()), list):
        raise BuildCheckError("invalid_input", "apply requires a Circuit JSON element array")
    if sha256_file(circuit) != manifest.circuit_json_hash:
        raise BuildCheckError("stale_input", "Circuit JSON no longer matches the manifest")
    if manifest.source_path:
        source = Path(manifest.source_path)
        source = _no_symlink_path(source if source.is_absolute() else manifest_path.parent / source)
        _require_bounded_regular_file(source, "source", limits.max_source_bytes)
        if sha256_file(source) != manifest.source_hash:
            raise BuildCheckError("stale_input", "source no longer matches the manifest")
    if expected_revision is not None and (not isinstance(expected_revision, str) or not expected_revision.strip()):
        raise BuildCheckError("invalid_input", "expected_revision must be a non-empty string")
    from .launch import discover_phicad_executable

    executable = config.apply_executable or discover_phicad_executable(project_root)
    command: Tuple[str, ...] = ()
    plan_path = output_dir / "plan.json"
    output_manifest = output_dir / "design.manifest.json"
    # A read-only plan must not follow native input symlinks either.
    if project_root.is_dir():
        for native in project_root.glob("*.kicad_*"):
            _require_bounded_regular_file(native, "native project input", limits.max_output_bytes)
    _prepare_output_dir(output_dir)
    reason = None
    plan = None
    returncode = None
    if not project_root.is_dir() or (project.suffix == ".kicad_pro" and not project.is_file()):
        reason = "native project is unavailable"
    elif not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        reason = "native PhiCad executable is unavailable (PATH, sibling checkout or apply_cli.executable)"
    else:
        command = (executable, "core", "apply", "--circuit-json", str(circuit),
                   "--project", str(project), "--plan", str(plan_path))
        if expected_revision is not None:
            command += ("--expected-revision", expected_revision)
        child_config = VerifyCliConfig(command=command, limits=limits)
        returncode, stdout, _stderr = await _run_process(command, child_config)
        _validate_output_tree(output_dir, limits)
        if plan_path.is_file():
            plan = _parse_apply_plan(plan_path, manifest.circuit_json_hash, project_root, returncode)
            if expected_revision is not None and plan["status"] == "planned" and plan["project"]["base_revision"] != expected_revision:
                raise BuildCheckError("stale_apply_plan", "planned revision differs from requested revision")
        else:
            # The implemented JS boundary can return a nested unavailable result on
            # stdout without creating either file. Older builds may only print usage.
            reason = "PhiCad did not produce plan.json; core apply may be unsupported (exit %s)" % returncode
            try:
                service = json.loads(stdout)
                failure = service.get("result", {})
                if (failure.get("schema") == "io.github.couplet-physical-ai.phicad.apply-result/v1"
                        and failure.get("status") == "unavailable" and isinstance(failure.get("reason"), str)):
                    reason = failure["reason"]
            except (ValueError, AttributeError):
                pass
    if plan is None:
        state = NativeApply(rejections=({"code": "apply_unavailable", "element": "project", "detail": reason},))
    else:
        state = NativeApply(status=plan["status"], plan_hash=plan["plan_hash"], plan_path="plan.json",
                            base_revision=plan["project"]["base_revision"], rejections=plan["rejections"])
    configuration = dict(manifest.configuration)
    artifact_root = Path(configuration.get("artifact_root") or manifest_path.parent)
    if not artifact_root.is_absolute():
        artifact_root = manifest_path.parent / artifact_root
    configuration["artifact_root"] = str(artifact_root.resolve())
    configuration["apply_plan"] = {"command": list(command), "limits": limits.to_dict(),
                                   "gate": APPLY_COMMIT_GATE, "input_manifest_sha256": sha256_file(manifest_path)}
    if manifest.compatibility_notes:
        configuration["compatibility_notes"] = list(manifest.compatibility_notes)
    native = manifest.native_artifact
    if native.path and not Path(native.path).is_absolute():
        native = replace(native, path=str((manifest_path.parent / native.path).resolve()))
    updated = replace(manifest, manifest_version=MANIFEST_SCHEMA_VERSION, native_apply=state,
                      source_path=str(source) if manifest.source_path else None,
                      circuit_json_path=str(circuit), native_artifact=native,
                      tool_versions=native_tool_versions(manifest.tool_versions), configuration=configuration,
                      manifest_hash=None)
    write_manifest(updated, output_manifest)
    _validate_output_tree(output_dir, limits)
    return {"status": state.status if plan else "unavailable", "reason": reason,
            "native_apply": state.to_dict(), "manifest_path": str(output_manifest),
            "command": list(command), "returncode": returncode,
            "plan_path": str(plan_path) if plan else None}
