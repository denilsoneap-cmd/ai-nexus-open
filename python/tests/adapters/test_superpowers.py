from nexus.adapters.superpowers import make_skill_agent
from nexus.core import NexusCore


def test_skill_agent_calls_runner_with_mapped_skill_name():
    calls = []

    def fake_runner(skill_name: str, input: dict) -> dict:
        calls.append((skill_name, input))
        return {"skill_ran": skill_name}

    agent = make_skill_agent(
        name="Dev Agent",
        skill_map={"write_tests": "test-driven-development"},
        runner=fake_runner,
    )
    core = NexusCore()
    core.register(agent)

    result_envelope = core.route("write_tests", input={"file": "foo.py"})

    assert calls == [("test-driven-development", {"file": "foo.py"})]
    assert result_envelope["payload"]["output"] == {"skill_ran": "test-driven-development"}


def test_skill_agent_supports_multiple_objectives_with_distinct_skills():
    def fake_runner(skill_name: str, input: dict) -> dict:
        return {"skill": skill_name}

    agent = make_skill_agent(
        name="Dev Agent",
        skill_map={
            "write_tests": "test-driven-development",
            "debug": "systematic-debugging",
        },
        runner=fake_runner,
    )
    core = NexusCore()
    core.register(agent)

    tests_result = core.route("write_tests")
    debug_result = core.route("debug")

    assert tests_result["payload"]["output"]["skill"] == "test-driven-development"
    assert debug_result["payload"]["output"]["skill"] == "systematic-debugging"


def test_skill_agent_defaults_capabilities_to_skill_map_keys():
    agent = make_skill_agent(
        name="Dev Agent",
        skill_map={"write_tests": "test-driven-development"},
        runner=lambda skill, input: {},
    )
    assert agent.identity.capabilities == ["write_tests"]
