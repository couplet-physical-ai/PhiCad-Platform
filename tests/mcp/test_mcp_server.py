from __future__ import annotations

import asyncio
import json
from io import BytesIO

import pytest

from phicad_platform.mcp_protocol import (
    CORE_FAILURE,
    METHOD_NOT_FOUND,
    REQUEST_CANCELLED,
    REQUEST_TIMEOUT,
    RESULT_TOO_LARGE,
    TOOL_NOT_FOUND,
)
from phicad_platform.mcp_server import MCPServer, run_stdio

pytestmark = pytest.mark.mcp


def rpc(request_id: int, method: str, params: dict | None = None) -> bytes:
    value = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        value["params"] = params
    return (json.dumps(value) + "\n").encode("utf-8")


def responses(output: BytesIO) -> list[dict]:
    return [json.loads(line) for line in output.getvalue().splitlines() if line]


class FakeCore:
    def platform_capabilities(self):
        print("accidental core diagnostic")
        return {"verify": True, "network": False}

    def platform_doctor(self):
        return {"healthy": True}

    def platform_open_view(self, request):
        return {"opened": True, "request": request}

    def design_build_check(self, request):
        return {"buildable": True, "request": request}

    def design_manifest_verify(self, manifest):
        return {"valid": True, "manifest": manifest}


class FailingCore:
    def platform_doctor(self):
        raise RuntimeError("provider-token-must-not-cross-the-boundary")


class SlowCore:
    async def platform_doctor(self):
        await asyncio.sleep(10)
        return {"healthy": True}


class CancelledCore:
    async def platform_doctor(self):
        await asyncio.sleep(10)
        return {"healthy": True}


def call(server: MCPServer, request_id: int, name: str, arguments: dict | None = None) -> dict:
    return asyncio.run(
        server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
    )


def test_initialize_and_tools_list_expose_the_high_level_surface() -> None:
    server = MCPServer(core=FakeCore())
    initialized = asyncio.run(
        server.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
    )
    assert initialized["result"]["protocolVersion"] == "2024-11-05"
    assert initialized["result"]["capabilities"]["tools"]

    listed = asyncio.run(
        server.handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
    )
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert names == [
        "platform_capabilities",
        "platform_doctor",
        "platform_open_view",
        "design_build_check",
        "design_manifest_verify",
        "design_apply_plan",
    ]


def test_successful_tool_calls_delegate_to_the_narrow_core_contract() -> None:
    server = MCPServer(core=FakeCore())
    assert json.loads(call(server, 1, "platform_capabilities")["result"]["content"][0]["text"])[
        "network"
    ] is False
    assert call(server, 2, "platform_doctor")["result"]["structuredContent"] == {"healthy": True}
    assert call(server, 3, "platform_open_view", {"manifest_path": "/tmp/demo.json", "target_view": "docs"})["result"][
        "structuredContent"
    ]["request"]["target_view"] == "docs"
    assert call(server, 4, "design_build_check", {"design": "demo"})["result"][
        "structuredContent"
    ]["request"] == {"design": "demo"}
    assert call(server, 5, "design_manifest_verify", {"manifest": {"id": 1}})["result"][
        "structuredContent"
    ]["valid"] is True


def test_unknown_method_and_unknown_tool_are_stable_errors() -> None:
    server = MCPServer(core=FakeCore())
    unknown_method = asyncio.run(
        server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "nope"})
    )
    assert unknown_method["error"]["code"] == METHOD_NOT_FOUND

    unknown_tool = call(server, 2, "not_a_tool")
    assert unknown_tool["error"]["code"] == TOOL_NOT_FOUND


def test_core_failure_is_mapped_without_returning_exception_text() -> None:
    response = call(MCPServer(core=FailingCore()), 1, "platform_doctor")
    encoded = json.dumps(response)
    assert response["error"]["code"] == CORE_FAILURE
    assert response["error"]["data"] == {"tool": "platform_doctor", "reason": "failed"}
    assert "provider-token-must-not-cross-the-boundary" not in encoded


def test_result_limit_is_enforced() -> None:
    class LargeCore:
        def platform_capabilities(self):
            return {"payload": "x" * 1000}

    response = call(MCPServer(core=LargeCore(), max_result_bytes=100), 1, "platform_capabilities")
    assert response["error"]["code"] == RESULT_TOO_LARGE


def test_stdio_protocol_has_no_stdout_pollution_and_handles_malformed_json() -> None:
    incoming = (
        b"not json\n"
        + rpc(1, "initialize", {})
        + rpc(2, "tools/call", {"name": "platform_capabilities"})
        + b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
    )
    output = BytesIO()
    asyncio.run(run_stdio(BytesIO(incoming), output, server=MCPServer(core=FakeCore())))

    result = responses(output)
    assert result[0]["error"]["code"] == -32700
    assert result[1]["result"]["serverInfo"]["name"] == "phicad-platform"
    assert result[2]["result"]["content"]
    assert len(result) == 3
    # The fake core printed a diagnostic, but the response stream remains JSON.
    for line in output.getvalue().splitlines():
        json.loads(line)


def test_oversized_request_is_rejected_and_next_line_survives() -> None:
    request_limit = 200
    incoming = b"x" * (request_limit + 20) + b"\n" + rpc(2, "tools/list", {})
    output = BytesIO()
    asyncio.run(
        run_stdio(
            BytesIO(incoming),
            output,
            server=MCPServer(core=FakeCore()),
            max_request_bytes=request_limit,
        )
    )

    result = responses(output)
    assert result[0]["error"]["code"] == -32001
    assert result[1]["result"]["tools"]


def test_tool_timeout_is_cancellable() -> None:
    response = call(
        MCPServer(core=SlowCore(), timeout_seconds=0.01),
        1,
        "platform_doctor",
    )
    assert response["error"]["code"] == REQUEST_TIMEOUT


def test_cancellation_notification_returns_a_cancellation_error() -> None:
    incoming = (
        rpc(1, "tools/call", {"name": "platform_doctor"})
        + b'{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1}}\n'
    )
    output = BytesIO()
    asyncio.run(
        run_stdio(
            BytesIO(incoming),
            output,
            server=MCPServer(core=CancelledCore(), timeout_seconds=5),
        )
    )
    result = responses(output)
    assert result[0]["error"]["code"] == REQUEST_CANCELLED


def test_apply_commit_refusal_exposes_the_typed_gate() -> None:
    response = call(MCPServer(), 1, "design_apply_plan", {"commit": True})
    result = response["result"]
    assert result["isError"]
    assert result["structuredContent"]["error"]["code"] == "commit_refused"
    assert result["structuredContent"]["error"]["details"]["gate"] == "platform_native_apply_plan_only"


def test_apply_does_not_accept_caller_commands() -> None:
    response = call(MCPServer(), 1, "design_apply_plan", {"command": ["arbitrary"]})
    assert response["result"]["structuredContent"]["error"]["code"] == "invalid_request"


def test_apply_delegates_to_core_and_has_closed_schema() -> None:
    class ApplyCore:
        async def design_apply_plan(self, request):
            return {"status": "planned", "request": request}

    request = {"manifest_path": "/tmp/input.json", "project": "/tmp/native", "output_dir": "/tmp/out"}
    response = call(MCPServer(core=ApplyCore()), 1, "design_apply_plan", request)
    assert response["result"]["structuredContent"]["request"] == request
    from phicad_platform.mcp_server import TOOL_BY_NAME
    schema = TOOL_BY_NAME["design_apply_plan"].input_schema
    assert schema["additionalProperties"] is False
    assert "command" not in schema["properties"]
