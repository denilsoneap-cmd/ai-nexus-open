import pytest

from nexus.a2a import (
    NEXUS_EVIDENCE_EXTENSION,
    a2a_message_to_task,
    a2a_task_to_outcome,
    agent_card_to_identity,
    artifact_to_evidence,
    error_to_a2a_task,
    evidence_to_artifact,
    result_to_a2a_task,
    task_to_a2a_message,
    to_agent_card,
)
from nexus.identity import AgentIdentity
from nexus.protocol import ErrorPayload, Evidence, ProtocolError, Result, Task


def make_identity() -> AgentIdentity:
    return AgentIdentity(
        name="Tax Specialist",
        role="tax-analysis",
        capabilities=["tax_analysis", "legislation_search"],
        scope="network",
    )


def test_agent_card_round_trip():
    identity = make_identity()
    card = to_agent_card(identity)

    assert card["id"] == identity.agent_id
    assert card["provider"]["name"] == "Tax Specialist"
    assert {s["name"] for s in card["skills"]} == {"tax_analysis", "legislation_search"}
    assert NEXUS_EVIDENCE_EXTENSION in card["extensions"]

    restored = agent_card_to_identity(card)
    assert restored == identity


def test_agent_card_omits_url_by_default():
    card = to_agent_card(make_identity())
    assert "url" not in card


def test_agent_card_carries_url_when_given():
    card = to_agent_card(make_identity(), url="http://127.0.0.1:9999")
    assert card["url"] == "http://127.0.0.1:9999"


def test_task_to_a2a_message_carries_nexus_metadata():
    task = Task(id="task-1", objective="analyze_tax", input={"jurisdiction": "MG"},
                constraints=["max_cost_usd:0.50"], risk="high")
    message = task_to_a2a_message(task, context_id="ctx-1")

    assert message["taskId"] == "task-1"
    assert message["contextId"] == "ctx-1"
    assert message["metadata"]["nexus.objective"] == "analyze_tax"
    assert message["metadata"]["nexus.risk"] == "high"
    assert message["parts"][0]["structuredData"] == {"jurisdiction": "MG"}


def test_a2a_message_to_task_round_trip():
    task = Task(id="task-1", objective="analyze_tax", input={"jurisdiction": "MG"},
                constraints=["max_cost_usd:0.50"], risk="high", deadline="2026-09-11T15:00:00Z")
    message = task_to_a2a_message(task)
    restored = a2a_message_to_task(message)
    assert restored == task


def test_a2a_message_to_task_requires_objective_metadata():
    with pytest.raises(ProtocolError):
        a2a_message_to_task({"messageId": "m1", "role": "agent", "parts": [], "metadata": {}})


def test_evidence_artifact_round_trip():
    evidence = Evidence(claim="rate is 18%", source="official.gov.br", agent_id="agent:tax",
                        transformation="extracted_verbatim", confidence=0.97, location="Article 15")
    artifact = evidence_to_artifact(evidence)
    assert artifact["extension"] == NEXUS_EVIDENCE_EXTENSION

    restored = artifact_to_evidence(artifact)
    assert restored == evidence


def test_artifact_to_evidence_rejects_non_nexus_artifact():
    with pytest.raises(ProtocolError):
        artifact_to_evidence({"id": "a1", "parts": [{"structuredData": {}}]})


def test_result_to_a2a_task_and_back():
    evidence = Evidence(claim="rate is 18%", source="official.gov.br", agent_id="agent:tax",
                        transformation="extracted_verbatim", confidence=0.97)
    result = Result(task_id="task-1", status="success", output={"tax_rate": 0.18},
                     confidence=0.94, evidence=[evidence])

    a2a_task = result_to_a2a_task(result, context_id="ctx-1")
    assert a2a_task["status"]["state"] == "COMPLETED"
    assert a2a_task["contextId"] == "ctx-1"

    restored = a2a_task_to_outcome(a2a_task)
    assert isinstance(restored, Result)
    assert restored.output == {"tax_rate": 0.18}
    assert restored.evidence[0].source == "official.gov.br"
    assert restored.confidence == 0.94


def test_a2a_task_to_outcome_merges_multiple_output_artifacts():
    """Regression: A2A does not limit a Task to one non-evidence artifact —
    an external A2A agent could return several. This used to let a later
    artifact silently clobber an earlier one instead of merging."""
    a2a_task = {
        "id": "task-1",
        "status": {"state": "COMPLETED"},
        "metadata": {"nexus.status": "success"},
        "artifacts": [
            {"id": "a1", "parts": [{"structuredData": {"tax_rate": 0.18}}]},
            {"id": "a2", "parts": [{"structuredData": {"jurisdiction": "MG"}}]},
        ],
    }
    restored = a2a_task_to_outcome(a2a_task)
    assert isinstance(restored, Result)
    assert restored.output == {"tax_rate": 0.18, "jurisdiction": "MG"}


def test_refused_result_maps_to_rejected_state():
    result = Result(task_id="task-1", status="refused", output={"reason": "out of scope"})
    a2a_task = result_to_a2a_task(result)
    assert a2a_task["status"]["state"] == "REJECTED"

    restored = a2a_task_to_outcome(a2a_task)
    assert isinstance(restored, Result)
    assert restored.status == "refused"


def test_error_to_a2a_task_and_back():
    error = ErrorPayload(task_id="task-1", error_code="capability_unavailable",
                          message="no agent", retryable=True)
    a2a_task = error_to_a2a_task(error)
    assert a2a_task["status"]["state"] == "FAILED"

    restored = a2a_task_to_outcome(a2a_task)
    assert isinstance(restored, ErrorPayload)
    assert restored.error_code == "capability_unavailable"
    assert restored.retryable is True


def test_a2a_task_to_outcome_rejects_non_terminal_state():
    with pytest.raises(ProtocolError):
        a2a_task_to_outcome({"id": "task-1", "status": {"state": "WORKING"}, "artifacts": []})
