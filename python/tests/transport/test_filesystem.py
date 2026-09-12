import pytest

from nexus.a2a import a2a_message_to_task, a2a_task_to_outcome
from nexus.protocol import Result, Task
from nexus.transport.filesystem import MESSAGE_ID_RE, FilesystemTransport, TransportError

SENDER = "agent:" + "a" * 32
RECEIVER = "agent:" + "b" * 32


def make_transport(tmp_path) -> FilesystemTransport:
    return FilesystemTransport(tmp_path / "bus")


def test_send_creates_message_in_receiver_inbox_with_valid_id(tmp_path):
    transport = make_transport(tmp_path)
    message_id = transport.send(SENDER, RECEIVER, {"hello": "world"})
    assert MESSAGE_ID_RE.fullmatch(message_id)
    assert transport._inbox(RECEIVER).joinpath(f"{message_id}.json").exists()


def test_pending_lists_message_for_receiver_only(tmp_path):
    transport = make_transport(tmp_path)
    transport.send(SENDER, RECEIVER, {"hello": "world"})
    assert len(transport.pending(RECEIVER)) == 1
    assert transport.pending(SENDER) == []


def test_pending_excludes_completed_messages(tmp_path):
    transport = make_transport(tmp_path)
    message_id = transport.send(SENDER, RECEIVER, {"hello": "world"})
    transport.claim(RECEIVER, message_id)
    transport.complete(RECEIVER, message_id)
    assert transport.pending(RECEIVER) == []


def test_claim_then_second_claim_raises(tmp_path):
    transport = make_transport(tmp_path)
    message_id = transport.send(SENDER, RECEIVER, {"hello": "world"})
    transport.claim(RECEIVER, message_id)
    with pytest.raises(TransportError):
        transport.claim(RECEIVER, message_id)


def test_claim_by_wrong_agent_raises(tmp_path):
    transport = make_transport(tmp_path)
    message_id = transport.send(SENDER, RECEIVER, {"hello": "world"})
    with pytest.raises(TransportError):
        transport.claim(SENDER, message_id)  # not addressed to SENDER


def test_release_allows_reclaiming(tmp_path):
    transport = make_transport(tmp_path)
    message_id = transport.send(SENDER, RECEIVER, {"hello": "world"})
    transport.claim(RECEIVER, message_id)
    transport.release(RECEIVER, message_id)
    assert not transport.is_claimed(RECEIVER, message_id)
    transport.claim(RECEIVER, message_id)  # should not raise


def test_complete_without_claim_raises(tmp_path):
    transport = make_transport(tmp_path)
    message_id = transport.send(SENDER, RECEIVER, {"hello": "world"})
    with pytest.raises(TransportError):
        transport.complete(RECEIVER, message_id)


def test_claim_after_completion_raises(tmp_path):
    transport = make_transport(tmp_path)
    message_id = transport.send(SENDER, RECEIVER, {"hello": "world"})
    transport.claim(RECEIVER, message_id)
    transport.complete(RECEIVER, message_id)
    with pytest.raises(TransportError):
        transport.claim(RECEIVER, message_id)


def test_send_with_invalid_responds_to_raises(tmp_path):
    transport = make_transport(tmp_path)
    with pytest.raises(TransportError):
        transport.send(SENDER, RECEIVER, {}, responds_to="not-a-valid-id")


def test_doctor_reports_root(tmp_path):
    transport = make_transport(tmp_path)
    report = transport.doctor()
    assert report["root"] == str(tmp_path / "bus")


def test_full_task_round_trip_through_transport(tmp_path):
    """End to end: a Task becomes an A2A message, travels through the
    filesystem transport, and is claimed/parsed back by the receiver."""
    transport = make_transport(tmp_path)
    task = Task(id="task-1", objective="analyze_tax", input={"jurisdiction": "MG"})

    message_id = transport.send_task(SENDER, RECEIVER, task)

    envelope = transport.claim(RECEIVER, message_id)
    assert envelope.kind == "message"
    restored_task = a2a_message_to_task(envelope.payload)
    assert restored_task == task

    result = Result(task_id=task.id, status="success", output={"tax_rate": 0.18})
    response_id = transport.send_result(RECEIVER, SENDER, result, responds_to=message_id)
    transport.complete(RECEIVER, message_id, response_id=response_id)

    response_envelope = transport.claim(SENDER, response_id)
    assert response_envelope.kind == "task"
    assert response_envelope.responds_to == message_id
    outcome = a2a_task_to_outcome(response_envelope.payload)
    assert isinstance(outcome, Result)
    assert outcome.output == {"tax_rate": 0.18}
