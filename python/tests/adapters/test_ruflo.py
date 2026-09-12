import os
import shutil

import pytest

from nexus.adapters.ruflo import list_agents, make_ruflo_agent
from nexus.core import NexusCore


def test_ruflo_agent_calls_runner_with_mapped_type():
    calls = []

    def fake_runner(agent_type: str, description: str, input: dict) -> dict:
        calls.append((agent_type, description, input))
        return {"spawned_type": agent_type, "echo": description}

    agent = make_ruflo_agent(
        name="Ruflo Coder",
        objective_agent_types={"write_code": "coder"},
        runner=fake_runner,
    )
    core = NexusCore()
    core.register(agent)

    result_envelope = core.route("write_code", input={"description": "add a login form"})

    assert calls == [("coder", "add a login form", {"description": "add a login form"})]
    assert result_envelope["payload"]["output"]["spawned_type"] == "coder"


def test_ruflo_agent_falls_back_to_objective_as_description():
    calls = []

    def fake_runner(agent_type: str, description: str, input: dict) -> dict:
        calls.append(description)
        return {}

    agent = make_ruflo_agent(name="Ruflo", objective_agent_types={"research_topic": "researcher"},
                              runner=fake_runner)
    core = NexusCore()
    core.register(agent)
    core.route("research_topic")  # no input.description supplied

    assert calls == ["research_topic"]


def test_ruflo_agent_defaults_capabilities_to_objective_keys():
    agent = make_ruflo_agent(
        name="Ruflo",
        objective_agent_types={"write_code": "coder", "research_topic": "researcher"},
        runner=lambda agent_type, description, input: {},
    )
    assert set(agent.identity.capabilities) == {"write_code", "research_topic"}


@pytest.mark.skipif(
    not os.environ.get("NEXUS_RUFLO_INTEGRATION"),
    reason="hits the real ruflo CLI (via npx if not installed) — set NEXUS_RUFLO_INTEGRATION=1 to run",
)
def test_list_agents_against_real_ruflo_cli():
    """Read-only, no LLM call — verified manually against a real `ruflo
    v3.41.2` install while writing this adapter. Opt-in because it still
    shells out to a real process (slow the first time via npx)."""
    result = list_agents(timeout=60)
    assert result["returncode"] == 0
    assert "Active Agents" in result["raw_output"] or "agent" in result["raw_output"].lower()
