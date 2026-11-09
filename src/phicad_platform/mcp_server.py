"""Credential-free stdio MCP server for PhiCad Platform.

The server is a thin protocol adapter.  It exposes platform-level operations
implemented by the installed PhiCad core and does not contain a model runtime,
network client, or credential-loading path.  If the core is not installed yet,
the tools remain discoverable and return a stable core-failure response.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import math
import sys
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

from .mcp_protocol import (
    CORE_FAILURE,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    MAX_REQUEST_BYTES,
    MAX_RESULT_BYTES,
    METHOD_NOT_FOUND,
    MISSING_ID,
    REQUEST_CANCELLED,
    REQUEST_TIMEOUT,
    REQUEST_TOO_LARGE,
    RESULT_TOO_LARGE,
    TOOL_NOT_FOUND,
    ProtocolError,
    Request,
    json_bytes,
    make_error_response,
    make_result_response,
    parse_request_line,
    parse_request_object,
    protocol_error_response,
)

LOGGER = logging.getLogger("phicad_platform.mcp")
_OVERSIZED_LINE = object()

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "phicad-platform"
SERVER_VERSION = "0.1.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 300.0

# This is the deliberately narrow core contract.  The core module, when it is
# available, exports six callables with these names.  Each callable accepts
# either no arguments, a single request mapping, or keyword fields from the
# request mapping and returns JSON-serializable data (sync or async).
CORE_MODULE_NAMES = ("phicad_platform.core",)
CORE_OPERATION_NAMES = (
    "platform_capabilities",
    "platform_doctor",
    "platform_open_view",
    "design_build_check",
    "design_manifest_verify",
    "design_apply_plan",
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": deepcopy(dict(self.input_schema)),
        }


_EMPTY_INPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_PASSTHROUGH_INPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "description": "Arguments are passed unchanged to the PhiCad core operation.",
    "additionalProperties": True,
}
_OPEN_VIEW_INPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["manifest_path", "target_view"],
    "properties": {
        "manifest_path": {"type": "string", "description": "Absolute path to a versioned design manifest."},
        "target_view": {
            "type": "string",
            "enum": ["phi", "studio", "circuit-source", "verify", "docs", "preview"],
        },
        "expected_manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "source_view": {"type": "string"},
        "focus": {"type": "boolean"},
        "dry_run": {"type": "boolean"},
    },
    "additionalProperties": False,
}

_APPLY_PLAN_INPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["manifest_path", "project", "output_dir"],
    "properties": {
        "manifest_path": {"type": "string"},
        "project": {"type": "string", "description": "Native project directory or .kicad_pro file."},
        "output_dir": {"type": "string", "description": "Fresh evidence directory outside the native project."},
        "expected_revision": {"type": "string"},
        "commit": {"type": "boolean", "description": "Must be false; true is refused at the plan-only gate."},
        "config_path": {"type": "string", "description": "Operator-managed Platform configuration file."},
    },
    "additionalProperties": False,
}

TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "platform_capabilities",
        "Report the capabilities exposed by this PhiCad Platform installation.",
        _EMPTY_INPUT_SCHEMA,
    ),
    ToolSpec(
        "platform_doctor",
        "Run the PhiCad Platform health and configuration checks.",
        _EMPTY_INPUT_SCHEMA,
    ),
    ToolSpec(
        "platform_open_view",
        "Open the same manifest-bound project in Phi, Studio, Circuit Source, Verify, Preview, or local Docs.",
        _OPEN_VIEW_INPUT_SCHEMA,
    ),
    ToolSpec(
        "design_build_check",
        "Check whether a design can be built by the PhiCad Platform.",
        _PASSTHROUGH_INPUT_SCHEMA,
    ),
    ToolSpec(
        "design_manifest_verify",
        "Verify a design manifest using the PhiCad Platform verification rules.",
        _PASSTHROUGH_INPUT_SCHEMA,
    ),
    ToolSpec(
        "design_apply_plan",
        "Plan Circuit JSON native application; never commit or claim an applied revision.",
        _APPLY_PLAN_INPUT_SCHEMA,
    ),
)
TOOL_BY_NAME = {tool.name: tool for tool in TOOLS}
ZERO_ARGUMENT_TOOLS = {"platform_capabilities", "platform_doctor"}


class CoreUnavailableError(RuntimeError):
    """Raised when the optional PhiCad core contract is not installed."""

    def __init__(self, operation: str) -> None:
        super().__init__(operation)
        self.operation = operation


class CoreInvocationError(RuntimeError):
    """Raised when a core operation fails without exposing its details."""

    def __init__(self, operation: str) -> None:
        super().__init__(operation)
        self.operation = operation


class ResultTooLargeError(RuntimeError):
    """Raised before a core result can cross the bounded protocol boundary."""

    def __init__(self, operation: str) -> None:
        super().__init__(operation)
        self.operation = operation


class _InstalledCore:
    """Narrow request adapter for the deterministic platform core.

    This class translates MCP JSON objects into the public core contracts.  It
    intentionally does not implement build, verification, or diagnosis logic;
    those remain in ``orchestrator`` and ``manifest``.
    """

    @staticmethod
    def _project_and_config(arguments: Mapping[str, Any]) -> tuple[Any, Any]:
        from pathlib import Path

        project_value = arguments.get("project_dir")
        project_dir = Path(project_value).expanduser().resolve() if project_value else Path.cwd()
        config_value = arguments.get("config_path", arguments.get("config"))
        config_path = Path(config_value).expanduser().resolve() if config_value else None
        return project_dir, config_path

    def platform_capabilities(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        from .cli import _capabilities
        from .orchestrator import load_platform_config

        project_dir, config_path = self._project_and_config(arguments)
        config = None
        if config_path or arguments.get("include_configuration"):
            config = load_platform_config(config_path, project_dir)
        return _capabilities(config)

    def platform_doctor(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        from .orchestrator import doctor, load_platform_config

        project_dir, config_path = self._project_and_config(arguments)
        return doctor(load_platform_config(config_path, project_dir))

    async def design_build_check(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        from pathlib import Path

        from .contracts import BuildCheckRequest
        from .orchestrator import build_check, load_platform_config

        project_dir, config_path = self._project_and_config(arguments)
        source = Path(arguments["source"]).expanduser().resolve()
        circuit_json = Path(arguments["circuit_json"]).expanduser().resolve()
        output_dir = Path(arguments["output_dir"]).expanduser().resolve()
        manifest_value = arguments.get("manifest_path", arguments.get("manifest"))
        manifest_path = (
            Path(manifest_value).expanduser().resolve()
            if manifest_value
            else output_dir / "design.manifest.json"
        )
        design_id = str(arguments.get("design_id") or source.stem)
        studio_value = arguments.get("native_artifact_path", arguments.get("studio_path", arguments.get("studio")))
        request = BuildCheckRequest(
            source=source,
            circuit_json=circuit_json,
            output_dir=output_dir,
            manifest_path=manifest_path,
            design_id=design_id,
            studio_revision=str(arguments.get("native_revision", arguments.get("studio_revision", ""))),
            studio_path=Path(studio_value).expanduser().resolve() if studio_value else None,
            studio_hash=arguments.get("native_artifact_hash", arguments.get("studio_hash")),
            approval_state=str(arguments.get("approval_state", "pending")),
        )
        result = await build_check(request, load_platform_config(config_path, project_dir))
        return result.to_dict()

    async def design_apply_plan(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        from pathlib import Path

        from .orchestrator import APPLY_COMMIT_GATE, BuildCheckError, design_apply_plan, load_platform_config

        try:
            if arguments.get("commit", False) is not False:
                raise BuildCheckError("commit_refused", "native commit is disabled at gate " + APPLY_COMMIT_GATE,
                                      {"gate": APPLY_COMMIT_GATE})
            if set(arguments) - set(_APPLY_PLAN_INPUT_SCHEMA["properties"]):
                raise BuildCheckError("invalid_request", "unsupported apply-plan arguments")
            for name in ("manifest_path", "project", "output_dir"):
                if not isinstance(arguments.get(name), str) or not arguments[name]:
                    raise BuildCheckError("invalid_request", "%s is required" % name)
            config_path = Path(arguments["config_path"]) if arguments.get("config_path") else None
            return await design_apply_plan(
                manifest_path=Path(arguments["manifest_path"]), project=Path(arguments["project"]),
                output_dir=Path(arguments["output_dir"]), expected_revision=arguments.get("expected_revision"),
                config=load_platform_config(config_path),
            )
        except BuildCheckError as exc:
            return {"error": exc.to_dict()}

    def platform_open_view(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        from .launch import open_view

        return open_view(**dict(arguments))

    def design_manifest_verify(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        from pathlib import Path

        from .manifest import verify_manifest

        manifest_value = arguments.get("path", arguments.get("manifest_path", arguments.get("manifest")))
        if not manifest_value:
            raise ValueError("manifest path is required")
        verify_files = arguments.get("verify_files")
        if verify_files is None:
            verify_files = not bool(arguments.get("no_file_check", False))
        if not isinstance(verify_files, bool):
            raise ValueError("verify_files must be a boolean")
        return verify_manifest(Path(manifest_value).expanduser().resolve(), verify_files=verify_files).to_dict()


def _discover_core() -> Any | None:
    """Load the optional installed core contract without reading the env."""

    for module_name in CORE_MODULE_NAMES:
        try:
            with redirect_stdout(sys.stderr):
                return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            # A missing candidate is the expected no-core case.  If a present
            # candidate itself imports a missing dependency, do not hide that
            # distinction behind another import attempt.
            if exc.name != module_name:
                LOGGER.warning("PhiCad core could not be loaded")
                return _InstalledCore()
        except Exception:
            # Import failures are intentionally not surfaced with exception
            # text: a provider credential or path must never reach the client.
            LOGGER.warning("PhiCad core could not be loaded")
            return _InstalledCore()
    return _InstalledCore()


def _find_operation(core: Any, operation: str) -> Callable[..., Any] | None:
    if isinstance(core, Mapping):
        candidate = core.get(operation)
    else:
        candidate = getattr(core, operation, None)
    return candidate if callable(candidate) else None


def _invocation_shape(
    function: Callable[..., Any], arguments: Mapping[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Adapt the narrow mapping contract to common core function signatures."""

    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        # A C extension or opaque callable can still use the documented
        # keyword contract.
        return (), dict(arguments)

    parameters = list(signature.parameters.values())
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    named = {
        parameter.name
        for parameter in parameters
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    required_positional = [
        parameter
        for parameter in positional
        if parameter.default is inspect.Parameter.empty
    ]

    if not arguments and not required_positional:
        return (), {}
    if has_var_keyword:
        return (), dict(arguments)
    if arguments and set(arguments).issubset(named):
        return (), dict(arguments)
    if len(positional) == 1:
        # `request`, `params`, `arguments`, and `input` are common names for
        # the single mapping form.  For an unknown single positional name,
        # using the mapping is the least surprising compatibility behaviour.
        return (dict(arguments),), {}
    return (), dict(arguments)


def _call_sync_quietly(
    function: Callable[..., Any], args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> Any:
    # Core code is not supposed to print, but keeping stdout reserved for the
    # JSON-RPC stream is a transport invariant.  Any accidental diagnostic is
    # moved to stderr rather than corrupting the client stream.
    with redirect_stdout(sys.stderr):
        return function(*args, **dict(kwargs))


async def _call_async_quietly(
    function: Callable[..., Any], args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> Any:
    with redirect_stdout(sys.stderr):
        value = function(*args, **dict(kwargs))
        if inspect.isawaitable(value):
            return await value
        return value


class CoreAdapter:
    """Invoke only the named core operations; never reimplement their work."""

    def __init__(self, core: Any | None = None) -> None:
        self._core = _discover_core() if core is None else core
        # redirect_stdout is process-global.  Serializing core calls keeps an
        # accidental print from racing another call and corrupting stdout.
        # Create the lock lazily: constructing asyncio primitives outside a
        # running loop is not portable across the Python versions supported by
        # the platform, and a server is also useful in repeated test loops.
        self._call_lock: asyncio.Lock | None = None
        self._call_loop: Any | None = None

    def _lock_for_current_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._call_lock is None or self._call_loop is not loop:
            self._call_loop = loop
            self._call_lock = asyncio.Lock()
        return self._call_lock

    async def call(self, operation: str, arguments: Mapping[str, Any]) -> Any:
        function = None if self._core is None else _find_operation(self._core, operation)
        if function is None:
            raise CoreUnavailableError(operation)

        args, kwargs = _invocation_shape(function, arguments)
        try:
            async with self._lock_for_current_loop():
                is_async = inspect.iscoroutinefunction(function) or inspect.iscoroutinefunction(
                    type(function).__call__
                )
                if is_async:
                    value = await _call_async_quietly(function, args, kwargs)
                else:
                    value = await asyncio.to_thread(
                        _call_sync_quietly, function, args, kwargs
                    )
                return value
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Keep the exception object as a cause for local debugging, but do
            # not serialize or log its message: it may contain sensitive paths
            # or values supplied by an underlying integration.
            raise CoreInvocationError(operation) from exc


class MCPServer:
    """MCP request dispatcher with a bounded, cancellable tool surface."""

    def __init__(
        self,
        *,
        core: Any | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_result_bytes: int = MAX_RESULT_BYTES,
    ) -> None:
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be finite and within the server limit")
        if max_result_bytes <= 0:
            raise ValueError("max_result_bytes must be positive")
        self.core = CoreAdapter(core)
        self.timeout_seconds = float(timeout_seconds)
        self.max_result_bytes = int(max_result_bytes)
        self.initialized = False

    async def handle_request(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Handle a decoded request object, returning its response if any."""

        try:
            request = parse_request_object(message)
        except ProtocolError as error:
            return protocol_error_response(error)
        return await self.handle_parsed_request(request)

    async def handle_parsed_request(self, request: Request) -> dict[str, Any] | None:
        if request.is_notification:
            # The stdio runner handles cancellation notifications because it
            # owns the in-flight task table.  All other notifications are
            # intentionally response-free per JSON-RPC.
            return None

        try:
            response = await self._dispatch(request)
        except asyncio.CancelledError:
            raise
        except Exception:
            # This is a final protocol guard.  Deliberately do not expose the
            # exception text or traceback to either stdout or the client.
            LOGGER.warning("Unhandled MCP request failure")
            response = make_error_response(request.request_id, INTERNAL_ERROR, "Internal error")
        return self._bound_response(response)

    async def _dispatch(self, request: Request) -> dict[str, Any]:
        if request.method == "initialize":
            return self._initialize(request)
        if request.method == "tools/list":
            return self._tools_list(request)
        if request.method == "tools/call":
            return await self._tools_call(request)
        if request.method in {"notifications/initialized", "notifications/cancelled"}:
            # These normally arrive without an id.  An id-bearing form is
            # accepted as a harmless compatibility response.
            return make_result_response(request.request_id, {})
        return make_error_response(request.request_id, METHOD_NOT_FOUND, "Method not found")

    def _require_object_params(self, request: Request) -> Mapping[str, Any] | None:
        if request.params is None:
            return {}
        if not isinstance(request.params, dict):
            return None
        return request.params

    def _initialize(self, request: Request) -> dict[str, Any]:
        params = self._require_object_params(request)
        if params is None:
            return make_error_response(request.request_id, INVALID_PARAMS, "Invalid params")
        self.initialized = True
        return make_result_response(
            request.request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    def _tools_list(self, request: Request) -> dict[str, Any]:
        params = self._require_object_params(request)
        if params is None:
            return make_error_response(request.request_id, INVALID_PARAMS, "Invalid params")
        return make_result_response(
            request.request_id,
            {"tools": [tool.as_dict() for tool in TOOLS]},
        )

    async def _tools_call(self, request: Request) -> dict[str, Any]:
        params = self._require_object_params(request)
        if params is None:
            return make_error_response(request.request_id, INVALID_PARAMS, "Invalid params")

        name = params.get("name")
        if not isinstance(name, str) or not name:
            return make_error_response(request.request_id, INVALID_PARAMS, "Invalid params")
        if name not in TOOL_BY_NAME:
            return make_error_response(
                request.request_id,
                TOOL_NOT_FOUND,
                "Tool not found",
                data={"tool": name},
            )

        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return make_error_response(request.request_id, INVALID_PARAMS, "Invalid params")
        if name in ZERO_ARGUMENT_TOOLS and arguments:
            return make_error_response(request.request_id, INVALID_PARAMS, "Invalid params")

        try:
            value = await asyncio.wait_for(
                self.core.call(name, arguments), timeout=self.timeout_seconds
            )
            result = self._tool_result(name, value)
            return make_result_response(request.request_id, result)
        except asyncio.TimeoutError:
            LOGGER.warning("MCP tool timed out: %s", name)
            return make_error_response(
                request.request_id,
                REQUEST_TIMEOUT,
                "Tool request timed out",
                data={"tool": name},
            )
        except asyncio.CancelledError:
            raise
        except ResultTooLargeError:
            return make_error_response(
                request.request_id,
                RESULT_TOO_LARGE,
                "Result is too large",
                data={"tool": name},
            )
        except (CoreUnavailableError, CoreInvocationError) as exc:
            reason = "unavailable" if isinstance(exc, CoreUnavailableError) else "failed"
            LOGGER.warning("MCP core operation %s: %s", reason, name)
            return make_error_response(
                request.request_id,
                CORE_FAILURE,
                "Core operation failed",
                data={"tool": name, "reason": reason},
            )
        except Exception:
            LOGGER.warning("MCP tool failure: %s", name)
            return make_error_response(
                request.request_id,
                CORE_FAILURE,
                "Core operation failed",
                data={"tool": name, "reason": "failed"},
            )

    def _tool_result(self, operation: str, value: Any) -> dict[str, Any]:
        try:
            encoded = json_bytes(value)
        except ProtocolError as exc:
            raise CoreInvocationError(operation) from exc
        if len(encoded) > self.max_result_bytes:
            raise ResultTooLargeError(operation)

        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CoreInvocationError(operation) from exc

        result: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "isError": isinstance(value, dict) and "error" in value,
        }
        # MCP structuredContent is an object.  Preserve the core's object
        # result for clients that want typed data; content remains the portable
        # JSON text representation for every JSON value.
        if isinstance(value, dict):
            result["structuredContent"] = value
        return result

    def _bound_response(self, response: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json_bytes(response)
        except ProtocolError:
            return make_error_response(
                response.get("id"), INTERNAL_ERROR, "Unable to encode JSON"
            )
        if len(encoded) <= self.max_result_bytes:
            return response
        return make_error_response(
            response.get("id"), RESULT_TOO_LARGE, "Result is too large"
        )


async def _readline(stream: Any, limit: int) -> bytes | str:
    reader = stream.readline
    if inspect.iscoroutinefunction(reader):
        return await reader(limit)
    return await asyncio.to_thread(reader, limit)


async def _read_bounded_line(stream: Any, max_request_bytes: int) -> bytes | None | object:
    """Read one line, returning None for EOF and a sentinel for oversize."""

    raw = await _readline(stream, max_request_bytes + 1)
    if raw in (b"", ""):
        return None
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw

    payload = raw_bytes[:-1] if raw_bytes.endswith(b"\n") else raw_bytes
    if payload.endswith(b"\r"):
        payload = payload[:-1]
    if len(payload) <= max_request_bytes:
        return raw_bytes

    # Discard the remainder of the physical line so the next request starts
    # at a JSON boundary.  The chunks are bounded even when a peer sends no
    # newline at all.
    while not raw_bytes.endswith(b"\n"):
        chunk = await _readline(stream, 64 * 1024)
        if chunk in (b"", ""):
            break
        if isinstance(chunk, str):
            chunk_bytes = chunk.encode("utf-8")
        else:
            chunk_bytes = chunk
        raw_bytes = chunk_bytes
    return _OVERSIZED_LINE


async def _write_response(stream: Any, response: Mapping[str, Any], lock: asyncio.Lock) -> None:
    encoded = json_bytes(response) + b"\n"
    async with lock:
        def write() -> None:
            try:
                stream.write(encoded)
            except TypeError:
                # Permit embedding with a text stream while keeping the real
                # launcher on binary stdin/stdout.
                stream.write(encoded.decode("utf-8"))
            flush = getattr(stream, "flush", None)
            if callable(flush):
                flush()

        await asyncio.to_thread(write)


async def run_stdio(
    input_stream: Any | None = None,
    output_stream: Any | None = None,
    *,
    server: MCPServer | None = None,
    max_request_bytes: int = MAX_REQUEST_BYTES,
) -> None:
    """Run the line-delimited JSON-RPC loop until stdin reaches EOF."""

    if max_request_bytes <= 0:
        raise ValueError("max_request_bytes must be positive")
    input_stream = input_stream if input_stream is not None else getattr(sys.stdin, "buffer", sys.stdin)
    output_stream = output_stream if output_stream is not None else getattr(
        sys.stdout, "buffer", sys.stdout
    )
    server = server if server is not None else MCPServer()

    output_lock = asyncio.Lock()
    pending: MutableMapping[Any, asyncio.Task[None]] = {}

    async def process(request: Request) -> None:
        current = asyncio.current_task()
        try:
            response = await server.handle_parsed_request(request)
        except asyncio.CancelledError:
            response = make_error_response(
                request.request_id, REQUEST_CANCELLED, "Request cancelled"
            )
        except Exception:
            LOGGER.warning("Unhandled MCP task failure")
            response = make_error_response(request.request_id, INTERNAL_ERROR, "Internal error")
        if response is not None:
            await _write_response(output_stream, response, output_lock)
        if pending.get(request.request_id) is current:
            pending.pop(request.request_id, None)

    async def cancel_request(request_id: Any) -> None:
        task = pending.get(request_id)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    while True:
        line = await _read_bounded_line(input_stream, max_request_bytes)
        if line is None:
            break
        # Never feed an oversized payload to json.loads.
        if line is _OVERSIZED_LINE:
            await _write_response(
                output_stream,
                protocol_error_response(ProtocolError(REQUEST_TOO_LARGE, "Request is too large")),
                output_lock,
            )
            continue

        try:
            request = parse_request_line(line, max_request_bytes=max_request_bytes)
        except ProtocolError as error:
            await _write_response(output_stream, protocol_error_response(error), output_lock)
            continue

        if request.is_notification:
            if request.method == "notifications/cancelled" and isinstance(request.params, dict):
                request_id = request.params.get("requestId", MISSING_ID)
                if request_id is not MISSING_ID:
                    await cancel_request(request_id)
            # notifications/initialized and unknown notifications do not have
            # responses under JSON-RPC.
            continue

        if request.request_id in pending:
            await _write_response(
                output_stream,
                make_error_response(request.request_id, INVALID_PARAMS, "Duplicate request id"),
                output_lock,
            )
            continue
        pending[request.request_id] = asyncio.create_task(process(request))

    if pending:
        await asyncio.gather(*tuple(pending.values()), return_exceptions=True)


def main() -> int:
    """CLI entry point used by ``bin/phicad-platform-mcp``."""

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_stdio())
    except KeyboardInterrupt:
        return 130
    return 0


__all__ = [
    "CORE_MODULE_NAMES",
    "CORE_OPERATION_NAMES",
    "CoreAdapter",
    "CoreInvocationError",
    "CoreUnavailableError",
    "MCPServer",
    "MCP_PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "TOOL_BY_NAME",
    "TOOLS",
    "main",
    "run_stdio",
]


if __name__ == "__main__":  # pragma: no cover - exercised by the launcher
    raise SystemExit(main())
