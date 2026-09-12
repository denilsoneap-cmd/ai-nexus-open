"""Level 2 (Nexus Core) dogfood adapter for Ruflo
(github.com/ruvnet/ruflo, already configured in this workspace:
`.claude-flow/`, `.swarm/`, `.mcp.json`) — the milestone ROADMAP.md and
ARCHITECTURE.md have flagged as open since Level 2 was first scaffolded:
routing a Nexus task to a real Ruflo-spawned agent instead of an in-process
Python handler.

`ruflo agent spawn -t <type> --task <description>` runs a real LLM call
through whatever provider Ruflo is configured for (Anthropic by default) —
slow, network- and credential-dependent, and not free. Like
`nexus.adapters.superpowers`, this module takes an injectable `runner`
callable so the Nexus<->Agent wiring can be tested with a fake at zero cost;
real use points `runner` at `cli_runner` (provided here), which shells out
to the actual CLI via `subprocess` (falling back to `npx -y ruflo@latest` if
`ruflo` isn't on PATH — confirmed working in this workspace, `ruflo v3.41.2`).

`list_agents()` is read-only (queries this workspace's local
`.claude-flow`/`.swarm` state) and safe to call for real — no LLM spend —
verified against the live CLI while writing this module.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from ..agent import Agent
from ..protocol import Task

RufloRunner = Callable[[str, str, dict[str, Any]], dict[str, Any]]


def _base_command() -> list[str]:
    """Prefer a globally installed `ruflo` if present; otherwise fall back
    to `npx -y ruflo@latest` (slower — npm resolves/caches the package on
    every cold run). Resolved via `shutil.which()` rather than passed as a
    bare name: on Windows, `npx`/`ruflo` are `.cmd` shims, and
    `subprocess.run` cannot locate those via PATH without either
    `shell=True` or the fully resolved (extension-included) path that
    `shutil.which` returns."""
    ruflo_path = shutil.which("ruflo")
    if ruflo_path:
        return [ruflo_path]
    npx_path = shutil.which("npx")
    if npx_path is None:
        raise RuntimeError("neither 'ruflo' nor 'npx' found on PATH")
    return [npx_path, "-y", "ruflo@latest"]


def cli_runner(agent_type: str, task_description: str, input: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    """Spawns a real Ruflo agent and hands it a task. Runs a real LLM call —
    do not call this from a test; use a fake `runner` instead (see the
    module tests for the pattern)."""
    command = [*_base_command(), "agent", "spawn", "-t", agent_type, "--task", task_description]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ruflo agent spawn failed (exit {result.returncode}): {result.stderr.strip()}")
    return {"raw_output": result.stdout.strip()}


def list_agents(timeout: int = 30) -> dict[str, Any]:
    """Read-only: lists agents Ruflo already knows about in this workspace.
    No LLM call, safe to run in tests/CI (still touches the local `ruflo`
    process, so callers needing a fully offline test should still fake it)."""
    command = [*_base_command(), "agent", "list"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return {"raw_output": result.stdout.strip(), "returncode": result.returncode}


def make_ruflo_agent(
    name: str,
    objective_agent_types: dict[str, str],
    runner: RufloRunner = cli_runner,
    capabilities: list[str] | None = None,
) -> Agent:
    """`objective_agent_types` maps a Nexus objective to the Ruflo agent
    type that should handle it, e.g. `{"write_code": "coder", "research":
    "researcher"}`. Each handler calls
    `runner(agent_type, description, task.input)`, where `description` is
    `task.input["description"]` if present, else `task.objective`."""
    agent = Agent(name=name, capabilities=capabilities or list(objective_agent_types))

    for objective, agent_type in objective_agent_types.items():

        def handler(task: Task, _agent_type: str = agent_type) -> dict[str, Any]:
            description = task.input.get("description") or task.objective
            return runner(_agent_type, description, task.input)

        agent.task(objective)(handler)

    return agent
