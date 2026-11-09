from __future__ import annotations

import json

import pytest

from phicad_platform.mcp_protocol import (
    INVALID_REQUEST,
    PARSE_ERROR,
    REQUEST_TOO_LARGE,
    ProtocolError,
    parse_request_line,
)

pytestmark = pytest.mark.mcp


def test_malformed_json_is_a_stable_parse_error() -> None:
    with pytest.raises(ProtocolError) as caught:
        parse_request_line(b'{"jsonrpc":"2.0",')

    assert caught.value.code == PARSE_ERROR
    assert caught.value.message == "Parse error"


def test_non_object_request_is_invalid() -> None:
    with pytest.raises(ProtocolError) as caught:
        parse_request_line(json.dumps(["not", "a", "request"]))

    assert caught.value.code == INVALID_REQUEST


def test_request_limit_is_in_bytes() -> None:
    with pytest.raises(ProtocolError) as caught:
        parse_request_line(b"x" * 8, max_request_bytes=7)

    assert caught.value.code == REQUEST_TOO_LARGE


def test_invalid_params_are_rejected_at_the_json_rpc_boundary() -> None:
    with pytest.raises(ProtocolError) as caught:
        parse_request_line(
            b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":"bad"}'
        )

    assert caught.value.code == -32602
