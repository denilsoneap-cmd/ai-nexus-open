import sys

import pytest

from nexus.adapters.mcp import (
    MCPError,
    StdioMCPTransport,
    call_tool,
    initialize,
    list_tools,
    make_mcp_agent,
)
from nexus.core import NexusCore

# A tiny, self-contained fake MCP server (JSON-RPC 2.0 over stdio, one
# message per line) so StdioMCPTransport can be tested against a real child
# process without depending on any actual MCP server implementation —
# same rigor this project applies to its HTTP adapters (a real local fake
# server, not a mock of urllib).
FAKE_MCP_SERVER = r"""
import sys, json

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "notifications/initialized":
        continue  # a notification carries no id and gets no response

    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake-mcp", "version": "0.0.1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "add", "description": "Add two numbers"}]}
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})
        if tool_name == "add":
            result = {"content": [{"type": "text", "text": str(args.get("a", 0) + args.get("b", 0))}], "isError": False}
        elif tool_name == "boom":
            result = {"content": [{"type": "text", "text": "tool failed"}], "isError": True}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"unknown tool {tool_name!r}"}}), flush=True)
            continue
    elif method == "wrong_id_once":
        print(json.dumps({"jsonrpc": "2.0", "id": msg_id + 1, "result": {}}), flush=True)
        continue
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"unknown method {method!r}"}}), flush=True)
        continue

    print(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}), flush=True)
"""


@pytest.fixture
def fake_server_transport():
    transport = StdioMCPTransport([sys.executable, "-c", FAKE_MCP_SERVER])
    yield transport
    transport.close()


def test_initialize_performs_handshake_and_returns_server_info(fake_server_transport):
    result = initialize(fake_server_transport)
    assert result["serverInfo"]["name"] == "fake-mcp"


def test_list_tools_returns_the_servers_tools(fake_server_transport):
    initialize(fake_server_transport)
    tools = list_tools(fake_server_transport)
    assert [t["name"] for t in tools] == ["add"]


def test_call_tool_returns_result_content(fake_server_transport):
    initialize(fake_server_transport)
    result = call_tool(fake_server_transport, "add", {"a": 2, "b": 3})
    assert result["content"][0]["text"] == "5"
    assert result["isError"] is False


def test_call_tool_reports_isError_without_raising(fake_server_transport):
    initialize(fake_server_transport)
    result = call_tool(fake_server_transport, "boom", {})
    assert result["isError"] is True


def test_request_raises_mcp_error_on_jsonrpc_error(fake_server_transport):
    initialize(fake_server_transport)
    with pytest.raises(MCPError):
        call_tool(fake_server_transport, "nonexistent_tool", {})


def test_request_raises_on_mismatched_response_id(fake_server_transport):
    with pytest.raises(MCPError):
        fake_server_transport.request("wrong_id_once")


def test_stdio_transport_raises_on_unstartable_command():
    with pytest.raises(MCPError):
        StdioMCPTransport(["definitely-not-a-real-executable-xyz"])


# --- make_mcp_agent: unit-tested against a fake MCPTransport (same
# injectable-seam pattern as nexus.adapters.ruflo's fake runner), no
# subprocess needed for these. ---


class FakeTransport:
    def __init__(self, results: dict[str, object] | None = None, raises: dict[str, Exception] | None = None):
        self.results = results or {}
        self.raises = raises or {}
        self.requests: list[tuple[str, dict]] = []
        self.notifications: list[tuple[str, dict]] = []

    def request(self, method, params=None):
        self.requests.append((method, params or {}))
        if method in self.raises:
            raise self.raises[method]
        return self.results.get(method)

    def notify(self, method, params=None):
        self.notifications.append((method, params or {}))


def test_make_mcp_agent_forwards_task_input_as_tool_arguments():
    transport = FakeTransport(results={
        "tools/call": {"content": [{"type": "text", "text": "5"}], "isError": False},
    })
    core = NexusCore()
    core.register(make_mcp_agent("Calc", {"add_numbers": "add"}, transport))

    result_envelope = core.route("add_numbers", input={"a": 2, "b": 3})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"]["text"] == "5"
    assert transport.requests == [("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}})]


def test_make_mcp_agent_fails_task_when_tool_reports_isError():
    transport = FakeTransport(results={
        "tools/call": {"content": [{"type": "text", "text": "division by zero"}], "isError": True},
    })
    core = NexusCore()
    core.register(make_mcp_agent("Calc", {"divide": "div"}, transport))

    result_envelope = core.route("divide", input={"a": 1, "b": 0})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "mcp_tool_reported_error"
    assert "division by zero" in result_envelope["payload"]["message"]


def test_make_mcp_agent_fails_task_when_transport_raises():
    transport = FakeTransport(raises={"tools/call": MCPError("server crashed")})
    core = NexusCore()
    core.register(make_mcp_agent("Calc", {"add_numbers": "add"}, transport))

    result_envelope = core.route("add_numbers", input={"a": 1, "b": 1})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "mcp_tool_error"
    assert result_envelope["payload"]["retryable"] is True


def test_make_mcp_agent_supports_multiple_objectives_on_one_transport():
    transport = FakeTransport(results={
        "tools/call": {"content": [{"type": "text", "text": "ok"}], "isError": False},
    })
    core = NexusCore()
    core.register(make_mcp_agent("Multi", {"op_a": "tool_a", "op_b": "tool_b"}, transport))

    assert core.route("op_a", input={})["message_type"] == "result"
    assert core.route("op_b", input={})["message_type"] == "result"
    assert [call[1]["name"] for call in transport.requests] == ["tool_a", "tool_b"]
