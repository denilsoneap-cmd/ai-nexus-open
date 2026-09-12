"""Level 11 (Workflow) — MCP transport binding, the open question RFC-0001
and RFC-0003 both flagged and left for this Level (RFC-0003 §Motivation:
"MCP remains a Level 11 concern"). MCP (Model Context Protocol) is a
model/agent-to-*tool* protocol, not an agent-to-agent one (that's A2A,
RFC-0003) — this module lets a Nexus `Agent` call out to tools exposed by
an MCP server, the same way `nexus.adapters.n8n` lets one call an n8n
webhook and `nexus.adapters.ruflo` lets one shell out to the Ruflo CLI.

`MCPTransport` is the injectable seam (same pattern as `ruflo.py`'s
`runner` and `superpowers.py`'s skill runner): a structural protocol, not a
concrete class, so `make_mcp_agent`'s tests never need to spawn a real MCP
server. `StdioMCPTransport` is the real implementation — MCP's standard
stdio binding, JSON-RPC 2.0 messages framed one-per-line over a child
process's stdin/stdout, which every MCP server (Python, Node, whatever)
speaks regardless of implementation language, matching `nexus.adapters.ruflo`'s
own precedent of shelling out via `subprocess` rather than depending on a
provider-specific SDK.

`initialize()` must be called once before any tool call — MCP's handshake
(`initialize` request, then an `initialized` notification) is not implicit
here; `make_mcp_agent` takes an already-initialized transport rather than
hiding the handshake, so one transport/process can be reused across several
agents/objectives without repeating it.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Protocol

from ..agent import Agent
from ..protocol import ErrorPayload, Task

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


class MCPTransport(Protocol):
    def request(self, method: str, params: dict[str, Any] | None = None) -> Any: ...
    def notify(self, method: str, params: dict[str, Any] | None = None) -> None: ...


class StdioMCPTransport:
    """Spawns an MCP server as a child process and speaks JSON-RPC 2.0 over
    its stdin/stdout, one message per line (MCP's stdio transport). Each
    `request()` blocks for exactly one reply matching the request's id —
    this project has no concurrent/async request needs yet, so a strictly
    synchronous request/response cycle (same simplicity as every other
    adapter's blocking `urllib`/`subprocess` call) is enough."""

    def __init__(self, command: list[str], timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._next_id = 1
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
            )
        except OSError as exc:
            raise MCPError(f"could not start MCP server {command!r}: {exc}") from exc

    def _write(self, message: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPError(f"MCP server's stdin is closed: {exc}") from exc

    def _read_line(self) -> dict[str, Any]:
        assert self._process.stdout is not None
        line = self._process.stdout.readline()
        if not line:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise MCPError(f"MCP server closed its stdout unexpectedly. stderr: {stderr.strip()}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP server sent a non-JSON line: {line!r}") from exc

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        message_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params or {}})
        response = self._read_line()
        if response.get("id") != message_id:
            raise MCPError(f"MCP response id {response.get('id')!r} does not match request id {message_id!r}")
        if "error" in response:
            error = response["error"]
            raise MCPError(f"MCP error {error.get('code')}: {error.get('message')}")
        return response.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        if self._process.stdin:
            self._process.stdin.close()
        self._process.terminate()


def initialize(
    transport: MCPTransport,
    client_name: str = "ai-nexus-open",
    client_version: str = "0.1.0",
) -> dict[str, Any]:
    """MCP's handshake: an `initialize` request (protocol version +
    capabilities + client identity) followed by an `initialized`
    notification. Returns the server's `initialize` result (its own
    `protocolVersion`/`capabilities`/`serverInfo`) for the caller to inspect
    if it needs to."""
    result = transport.request("initialize", {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": client_name, "version": client_version},
    })
    transport.notify("notifications/initialized")
    return result


def list_tools(transport: MCPTransport) -> list[dict[str, Any]]:
    result = transport.request("tools/list")
    return result.get("tools", [])


def call_tool(transport: MCPTransport, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return transport.request("tools/call", {"name": tool_name, "arguments": arguments})


def _extract_text(tool_result: dict[str, Any]) -> str:
    parts = tool_result.get("content", [])
    return "".join(part.get("text", "") for part in parts if part.get("type") == "text")


def make_mcp_agent(
    name: str,
    objective_tools: dict[str, str],
    transport: MCPTransport,
    capabilities: list[str] | None = None,
) -> Agent:
    """Build an Agent whose task handlers each call an MCP tool.
    `objective_tools` maps a Nexus objective to the MCP tool name that
    handles it, e.g. `{"search_docs": "search"}` — `task.input` is passed
    straight through as the tool's `arguments` (same "just forward the
    input" contract as `nexus.adapters.n8n.make_n8n_agent`).

    `transport` must already be initialized (see `initialize()`) — this
    factory does not perform the handshake itself, so one transport can
    back several agents/objectives without repeating it."""
    agent = Agent(name=name, capabilities=capabilities or list(objective_tools))

    for objective, tool_name in objective_tools.items():

        def handler(task: Task, _tool_name: str = tool_name) -> dict[str, Any] | ErrorPayload:
            try:
                tool_result = call_tool(transport, _tool_name, task.input)
            except MCPError as exc:
                return agent.fail(task, error_code="mcp_tool_error", message=str(exc), retryable=True)
            if tool_result.get("isError"):
                return agent.fail(
                    task, error_code="mcp_tool_reported_error",
                    message=_extract_text(tool_result) or f"MCP tool {_tool_name!r} reported an error",
                    retryable=False,
                )
            return {"text": _extract_text(tool_result), "raw": tool_result}

        agent.task(objective)(handler)

    return agent
