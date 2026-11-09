"""Small JSON-RPC 2.0 helpers for the PhiCad stdio MCP surface.

This module deliberately contains only transport and protocol concerns.  It has
no provider, network, or credential handling.  The server uses one JSON value
per input line and emits one JSON value per response line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Mapping

# These limits are byte limits, rather than character limits.  Keeping them in
# one place makes the stdio boundary auditable and easy for a caller to tune in
# tests without changing the protocol implementation.
MAX_REQUEST_BYTES: Final[int] = 1_048_576
MAX_RESULT_BYTES: Final[int] = 2_097_152

JSONRPC_VERSION: Final[str] = "2.0"

# JSON-RPC's standard errors plus a small, stable application range.  The
# application values deliberately stay inside the server-error range reserved
# by JSON-RPC.
PARSE_ERROR: Final[int] = -32700
INVALID_REQUEST: Final[int] = -32600
METHOD_NOT_FOUND: Final[int] = -32601
INVALID_PARAMS: Final[int] = -32602
INTERNAL_ERROR: Final[int] = -32603
REQUEST_TOO_LARGE: Final[int] = -32001
RESULT_TOO_LARGE: Final[int] = -32002
REQUEST_TIMEOUT: Final[int] = -32003
REQUEST_CANCELLED: Final[int] = -32004
TOOL_NOT_FOUND: Final[int] = -32005
CORE_FAILURE: Final[int] = -32010


# An absent id is different from an explicit JSON null id.  JSON-RPC permits
# null ids (though clients are discouraged from using them), so preserve that
# distinction while parsing.
MISSING_ID: Final[object] = object()


class ProtocolError(Exception):
    """An error that can be returned as a JSON-RPC error object."""

    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: Mapping[str, Any] | None = None,
        request_id: Any = MISSING_ID,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data) if data is not None else None
        self.request_id = request_id


@dataclass(frozen=True)
class Request:
    """The validated subset of a JSON-RPC request used by this server."""

    request_id: Any = MISSING_ID
    method: str = ""
    params: Any = None

    @property
    def is_notification(self) -> bool:
        return self.request_id is MISSING_ID


def _reject_non_json_constant(value: str) -> None:
    # json.loads accepts NaN and Infinity by default.  They are not JSON and
    # could make result-size and downstream validation behaviour surprising.
    raise ValueError(value)


def _decode_json(raw: bytes | str) -> Any:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(PARSE_ERROR, "Parse error") from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise ProtocolError(PARSE_ERROR, "Parse error")

    try:
        return json.loads(text, parse_constant=_reject_non_json_constant)
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError) as exc:
        raise ProtocolError(PARSE_ERROR, "Parse error") from exc


def _validate_request_id(request_id: Any) -> None:
    # bool is an int subclass but is not a JSON-RPC request id.
    if request_id is None or isinstance(request_id, (str, int, float)) and not isinstance(request_id, bool):
        return
    raise ProtocolError(INVALID_REQUEST, "Invalid Request")


def parse_request_object(value: Any) -> Request:
    """Validate and convert a decoded JSON-RPC request object.

    The method intentionally does not validate method-specific parameters;
    that belongs to the MCP server dispatcher.
    """

    if not isinstance(value, dict):
        raise ProtocolError(INVALID_REQUEST, "Invalid Request")
    if value.get("jsonrpc") != JSONRPC_VERSION:
        raise ProtocolError(INVALID_REQUEST, "Invalid Request")

    method = value.get("method", MISSING_ID)
    if not isinstance(method, str) or not method:
        raise ProtocolError(INVALID_REQUEST, "Invalid Request")

    request_id = value.get("id", MISSING_ID)
    if request_id is not MISSING_ID:
        _validate_request_id(request_id)

    params = value.get("params", None)
    if params is not None and not isinstance(params, (dict, list)):
        raise ProtocolError(
            INVALID_PARAMS,
            "Invalid params",
            request_id=request_id,
        )

    return Request(request_id=request_id, method=method, params=params)


def parse_request_line(
    raw: bytes | str,
    *,
    max_request_bytes: int = MAX_REQUEST_BYTES,
) -> Request:
    """Decode one bounded stdio line and validate its JSON-RPC envelope."""

    if isinstance(raw, bytes):
        payload = raw
        if payload.endswith(b"\n"):
            payload = payload[:-1]
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        size = len(payload)
    elif isinstance(raw, str):
        # This branch is useful for unit tests and direct embedding.  The
        # actual stdio loop reads bytes and therefore enforces byte limits.
        payload = raw.rstrip("\r\n")
        size = len(payload.encode("utf-8"))
    else:
        raise ProtocolError(PARSE_ERROR, "Parse error")

    if size > max_request_bytes:
        raise ProtocolError(REQUEST_TOO_LARGE, "Request is too large")

    return parse_request_object(_decode_json(payload))


def json_bytes(value: Any) -> bytes:
    """Serialize a protocol value with strict, compact JSON semantics."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError) as exc:
        raise ProtocolError(INTERNAL_ERROR, "Unable to encode JSON") from exc


def make_result_response(request_id: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC success response."""

    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def make_error_response(
    request_id: Any,
    code: int,
    message: str,
    *,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC error response without exposing exception details."""

    error: dict[str, Any] = {"code": int(code), "message": message}
    if data:
        error["data"] = dict(data)
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def protocol_error_response(error: ProtocolError) -> dict[str, Any]:
    """Build the response for a malformed or otherwise invalid request."""

    request_id = None if error.request_id is MISSING_ID else error.request_id
    return make_error_response(request_id, error.code, error.message, data=error.data)


__all__ = [
    "CORE_FAILURE",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "JSONRPC_VERSION",
    "MAX_REQUEST_BYTES",
    "MAX_RESULT_BYTES",
    "METHOD_NOT_FOUND",
    "MISSING_ID",
    "PARSE_ERROR",
    "ProtocolError",
    "REQUEST_CANCELLED",
    "REQUEST_TIMEOUT",
    "REQUEST_TOO_LARGE",
    "RESULT_TOO_LARGE",
    "Request",
    "TOOL_NOT_FOUND",
    "json_bytes",
    "make_error_response",
    "make_result_response",
    "parse_request_line",
    "parse_request_object",
    "protocol_error_response",
]
