#!/usr/bin/env python3
"""Small credential-free stdio endpoint used by the developer-preview launcher.

The platform implementation is deliberately not bundled by this installer.  This
endpoint gives Phi a valid, harmless MCP process while the preview components are
installed separately.  It never reads or forwards environment variables.
"""

from __future__ import annotations

import json
import sys
from typing import Any

SERVER_INFO = {
    "name": "phicad-platform",
    "version": "0.1.0-dev.1",
}


def _response(request_id: Any, result: Any) -> None:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        separators=(",", ":"),
    ).encode("utf-8")
    # MCP uses Content-Length framing on stdio.  Keeping all diagnostics on stderr
    # is important: stdout is the protocol stream.
    sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _error(request_id: Any, code: int, message: str) -> None:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        separators=(",", ":"),
    ).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _read_message() -> dict[str, Any] | None:
    """Read either MCP Content-Length framing or a newline JSON message."""
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    if first.lower().startswith(b"content-length:"):
        try:
            length = int(first.split(b":", 1)[1].strip())
        except ValueError:
            return None
        # Consume headers up to the blank line.
        while True:
            line = sys.stdin.buffer.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
        body = sys.stdin.buffer.read(length)
    else:
        body = first.rstrip(b"\r\n")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("--version", "-V"):
        print(SERVER_INFO["version"])
        return 0
    if argv and argv[0] in ("--help", "-h"):
        print("Credential-free PhiCad Platform developer-preview MCP stdio endpoint.")
        return 0

    while True:
        request = _read_message()
        if request is None:
            return 0
        request_id = request.get("id")
        method = request.get("method")
        if request_id is None and method == "notifications/initialized":
            continue
        if method == "initialize":
            _response(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            )
        elif method == "ping":
            _response(request_id, {})
        elif method == "tools/list":
            _response(request_id, {"tools": []})
        elif method == "tools/call":
            _error(request_id, -32601, "No platform tools are bundled in this developer preview")
        elif request_id is not None:
            _error(request_id, -32601, f"Unsupported method: {method}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
