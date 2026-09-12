import pytest

from nexus.protocol import (
    ErrorPayload,
    Evidence,
    ProtocolError,
    Result,
    Task,
    envelope,
    validate_envelope,
)


def test_envelope_round_trip_is_valid():
    msg = envelope(
        message_type="task",
        sender={"agent_id": "agent:" + "a" * 32},
        payload=Task(id="task-1", objective="analyze_tax").to_payload(),
    )
    validate_envelope(msg)
    assert msg["protocol"] == "nexus"
    assert msg["message_type"] == "task"
    assert msg["correlation_id"] is None


def test_envelope_rejects_unknown_message_type():
    with pytest.raises(ProtocolError):
        envelope(message_type="not-a-type", sender={"agent_id": "agent:x"}, payload={})


def test_validate_envelope_rejects_missing_protocol():
    with pytest.raises(ProtocolError):
        validate_envelope({"version": "1.1", "message_id": "m1", "message_type": "task",
                            "timestamp": "now", "sender": {"agent_id": "a"}, "payload": {}})


def test_validate_envelope_rejects_unsupported_major_version():
    msg = envelope(message_type="task", sender={"agent_id": "agent:x"}, payload={})
    msg["version"] = "2.0"
    with pytest.raises(ProtocolError):
        validate_envelope(msg)


def test_validate_envelope_accepts_newer_minor_version():
    msg = envelope(message_type="task", sender={"agent_id": "agent:x"}, payload={})
    msg["version"] = "1.99"
    validate_envelope(msg)  # should not raise


def test_task_payload_round_trip():
    task = Task(id="task-1", objective="analyze_tax_rule", input={"jurisdiction": "MG"},
                constraints=["max_cost_usd:0.50"], risk="high")
    restored = Task.from_payload(task.to_payload())
    assert restored == task


def test_task_rejects_invalid_risk():
    with pytest.raises(ProtocolError):
        Task(id="task-1", objective="x", risk="apocalyptic")


def test_result_payload_round_trip_with_evidence():
    ev = Evidence(claim="rate is 18%", source="official.gov.br", agent_id="agent:tax",
                  transformation="extracted_verbatim", confidence=0.97, location="Article 15")
    result = Result(task_id="task-1", status="success", output={"tax_rate": 0.18},
                     confidence=0.94, evidence=[ev])
    restored = Result.from_payload(result.to_payload())
    assert restored.output == {"tax_rate": 0.18}
    assert restored.evidence[0].source == "official.gov.br"


def test_result_rejects_invalid_status():
    with pytest.raises(ProtocolError):
        Result(task_id="task-1", status="maybe")


def test_evidence_rejects_confidence_out_of_range():
    with pytest.raises(ProtocolError):
        Evidence(claim="x", source="y", agent_id="agent:z",
                  transformation="computed", confidence=1.5)


def test_evidence_rejects_invalid_transformation():
    with pytest.raises(ProtocolError):
        Evidence(claim="x", source="y", agent_id="agent:z",
                  transformation="guessed", confidence=0.5)


def test_error_payload_round_trip():
    err = ErrorPayload(task_id="task-1", error_code="capability_unavailable",
                        message="no agent", retryable=True)
    restored = ErrorPayload.from_payload(err.to_payload())
    assert restored == err
