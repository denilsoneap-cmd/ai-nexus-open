from nexus.audit import GENESIS_HASH, AuditLog


def test_first_event_chains_to_genesis_hash():
    log = AuditLog()
    event = log.append(event_type="task", actor="agent:a", payload={"x": 1})
    assert event.previous_hash == GENESIS_HASH
    assert len(event.event_hash) == 64


def test_events_chain_to_previous_hash():
    log = AuditLog()
    first = log.append(event_type="task", actor="agent:a", payload={"x": 1})
    second = log.append(event_type="result", actor="agent:b", payload={"y": 2})
    assert second.previous_hash == first.event_hash


def test_verify_passes_on_untouched_log():
    log = AuditLog()
    log.append(event_type="task", actor="agent:a", payload={"x": 1})
    log.append(event_type="result", actor="agent:b", payload={"y": 2})
    assert log.verify() is True


def test_verify_fails_if_payload_tampered_after_append():
    log = AuditLog()
    log.append(event_type="task", actor="agent:a", payload={"x": 1})
    log._events[0].payload["x"] = 999  # simulate tampering with a stored event
    assert log.verify() is False


def test_verify_fails_if_event_removed():
    log = AuditLog()
    log.append(event_type="task", actor="agent:a", payload={"x": 1})
    log.append(event_type="result", actor="agent:b", payload={"y": 2})
    del log._events[0]
    assert log.verify() is False


def test_verify_fails_if_events_reordered():
    log = AuditLog()
    log.append(event_type="task", actor="agent:a", payload={"x": 1})
    log.append(event_type="result", actor="agent:b", payload={"y": 2})
    log._events.reverse()
    assert log.verify() is False


def test_events_returns_a_copy():
    log = AuditLog()
    log.append(event_type="task", actor="agent:a", payload={"x": 1})
    events = log.events()
    events.clear()
    assert len(log.events()) == 1
