import pytest

from nexus.identity import AgentIdentity, IdentityError, new_agent_id


def test_new_agent_id_matches_canonical_form():
    agent_id = new_agent_id()
    assert agent_id.startswith("agent:")
    assert len(agent_id) == len("agent:") + 32  # uuid4 hex


def test_new_agent_id_is_unique():
    assert new_agent_id() != new_agent_id()


def test_identity_defaults_to_project_scope():
    identity = AgentIdentity(name="Tax Specialist")
    assert identity.scope == "project"


def test_identity_rejects_invalid_scope():
    with pytest.raises(IdentityError):
        AgentIdentity(scope="galactic")


def test_identity_rejects_malformed_agent_id():
    with pytest.raises(IdentityError):
        AgentIdentity(agent_id="not-prefixed")


def test_minimal_form_only_has_agent_id():
    identity = AgentIdentity(name="Tax Specialist", capabilities=["tax_analysis"])
    minimal = identity.to_dict(minimal=True)
    assert set(minimal) == {"agent_id"}


def test_full_form_round_trip():
    identity = AgentIdentity(name="Tax Specialist", role="tax-analysis",
                              capabilities=["tax_analysis", "legislation_search"],
                              scope="network")
    restored = AgentIdentity.from_dict(identity.to_dict())
    assert restored == identity
