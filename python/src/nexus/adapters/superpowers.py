"""Adapter for agent-skill frameworks such as obra/superpowers
(github.com/obra/superpowers — a Claude Code skills marketplace: TDD,
isolated git worktrees, markdown-defined Skills).

Per ARCHITECTURE.md principle 1, Nexus does not call any specific
skill-runner API directly — that would make one skills framework load-bearing
in the core. Instead, `make_skill_agent` takes a `runner` callable injected
by the integrator: it can shell out to the `superpowers` CLI, invoke Claude
Code's own Skill tool, call a different framework entirely, or (as in tests)
be a fake. The resulting Agent is indistinguishable from any other to
`NexusCore` — it registers and routes exactly the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..agent import Agent
from ..protocol import Task

SkillRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


def make_skill_agent(
    name: str,
    skill_map: dict[str, str],
    runner: SkillRunner,
    capabilities: list[str] | None = None,
) -> Agent:
    """`skill_map` maps a Nexus objective (e.g. "write_tests") to a skill
    name (e.g. "test-driven-development"). Each handler calls
    `runner(skill_name, task.input)` and wraps the returned dict as output.
    """
    agent = Agent(name=name, capabilities=capabilities or list(skill_map))

    for objective, skill_name in skill_map.items():

        def handler(task: Task, _skill: str = skill_name) -> dict[str, Any]:
            return runner(_skill, task.input)

        agent.task(objective)(handler)

    return agent
