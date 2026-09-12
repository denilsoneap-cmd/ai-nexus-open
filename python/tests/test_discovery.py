import pytest

from nexus.agent import Agent
from nexus.discovery import FileRegistry, InMemoryRegistry, publish_agent


@pytest.fixture(params=["memory", "file"])
def registry(request, tmp_path):
    if request.param == "memory":
        return InMemoryRegistry()
    return FileRegistry(tmp_path / "registry")


def make_tax_agent() -> Agent:
    return Agent(name="Tax Specialist", capabilities=["tax_analysis", "legislation_search"])


def test_publish_and_get_round_trip(registry):
    agent = make_tax_agent()
    publish_agent(registry, agent)
    card = registry.get(agent.identity.agent_id)
    assert card["id"] == agent.identity.agent_id
    assert card["provider"]["name"] == "Tax Specialist"


def test_get_returns_none_for_unknown_agent(registry):
    assert registry.get("agent:" + "0" * 32) is None


def test_find_by_skill_matches_published_capability(registry):
    agent = make_tax_agent()
    publish_agent(registry, agent)
    found = registry.find_by_skill("tax_analysis")
    assert len(found) == 1
    assert found[0]["id"] == agent.identity.agent_id


def test_find_by_skill_excludes_agents_without_it(registry):
    tax_agent = make_tax_agent()
    other_agent = Agent(name="Other", capabilities=["unrelated"])
    publish_agent(registry, tax_agent)
    publish_agent(registry, other_agent)
    found = registry.find_by_skill("tax_analysis")
    assert [c["id"] for c in found] == [tax_agent.identity.agent_id]


def test_unpublish_removes_the_agent(registry):
    agent = make_tax_agent()
    publish_agent(registry, agent)
    registry.unpublish(agent.identity.agent_id)
    assert registry.get(agent.identity.agent_id) is None


def test_unpublish_unknown_agent_does_not_raise(registry):
    registry.unpublish("agent:" + "f" * 32)  # should not raise


def test_all_lists_every_published_card(registry):
    a = make_tax_agent()
    b = Agent(name="B", capabilities=["x"])
    publish_agent(registry, a)
    publish_agent(registry, b)
    assert {c["id"] for c in registry.all()} == {a.identity.agent_id, b.identity.agent_id}


def test_publishing_again_overwrites_not_duplicates(registry):
    agent = make_tax_agent()
    publish_agent(registry, agent)
    publish_agent(registry, agent)
    assert len(registry.all()) == 1


def test_file_registry_persists_across_instances(tmp_path):
    path = tmp_path / "registry"
    agent = make_tax_agent()
    publish_agent(FileRegistry(path), agent)

    reopened = FileRegistry(path)
    assert reopened.get(agent.identity.agent_id) is not None


def test_file_registry_sanitizes_path_traversal_in_agent_id(tmp_path):
    registry = FileRegistry(tmp_path / "registry")
    evil_card = {"id": "../../../../evil", "provider": {"name": "x"}, "skills": []}
    registry.publish(evil_card)
    # nothing should have escaped the registry directory
    assert not any(tmp_path.glob("evil*"))
    assert registry.get("../../../../evil") is not None  # still round-trips within the sandbox
