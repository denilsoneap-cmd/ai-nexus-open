from nexus.agent import Agent
from nexus.audit import AuditLog
from nexus.core import NexusCore
from nexus.protocol import Result, Task, validate_envelope
from nexus.trust import TrustEvaluator


def make_core_with_tax_agent() -> tuple[NexusCore, Agent]:
    core = NexusCore()
    agent = Agent(name="Tax Specialist", capabilities=["tax_analysis"])

    @agent.task("analyze_tax")
    def analyze(task: Task) -> dict:
        return {"tax_rate": 0.18, "jurisdiction": task.input.get("jurisdiction")}

    core.register(agent)
    return core, agent


def test_route_returns_result_envelope_from_capable_agent():
    core, agent = make_core_with_tax_agent()
    result_envelope = core.route("analyze_tax", input={"jurisdiction": "MG"})
    validate_envelope(result_envelope)
    assert result_envelope["message_type"] == "result"
    assert result_envelope["sender"]["agent_id"] == agent.identity.agent_id
    assert result_envelope["payload"]["output"]["tax_rate"] == 0.18


def test_route_correlation_id_matches_task_message_id():
    core, _ = make_core_with_tax_agent()
    result_envelope = core.route("analyze_tax", input={"jurisdiction": "MG"})
    task_envelope = core.trace[0]
    assert result_envelope["correlation_id"] == task_envelope["message_id"]


def test_route_returns_error_when_no_agent_registered():
    core = NexusCore()
    error_envelope = core.route("translate_document")
    validate_envelope(error_envelope)
    assert error_envelope["message_type"] == "error"
    assert error_envelope["payload"]["error_code"] == "capability_unavailable"


def test_trace_records_every_envelope_in_order():
    core, _ = make_core_with_tax_agent()
    core.route("analyze_tax", input={"jurisdiction": "MG"})
    assert [m["message_type"] for m in core.trace] == ["task", "result"]


def test_find_by_capability_matches_declared_capability():
    core, agent = make_core_with_tax_agent()
    assert core.find_by_capability("tax_analysis") == [agent]
    assert core.find_by_capability("unrelated") == []


def test_unregister_removes_agent_from_routing():
    core, agent = make_core_with_tax_agent()
    core.unregister(agent.identity.agent_id)
    error_envelope = core.route("analyze_tax")
    assert error_envelope["message_type"] == "error"


def test_route_picks_first_capable_agent_when_multiple_registered():
    core = NexusCore()

    agent_a = Agent(name="A", capabilities=["shared"])
    agent_b = Agent(name="B", capabilities=["shared"])

    @agent_a.task("shared_op")
    def handle_a(task: Task) -> dict:
        return {"handled_by": "A"}

    @agent_b.task("shared_op")
    def handle_b(task: Task) -> dict:
        return {"handled_by": "B"}

    core.register(agent_a)
    core.register(agent_b)

    result_envelope = core.route("shared_op")
    assert result_envelope["payload"]["output"]["handled_by"] == "A"


def test_route_with_audit_log_records_task_and_result_events():
    audit = AuditLog()
    core = NexusCore(audit=audit)
    agent = Agent(name="Tax Specialist", capabilities=["tax_analysis"])

    @agent.task("analyze_tax")
    def analyze(task: Task) -> dict:
        return {"tax_rate": 0.18}

    core.register(agent)
    core.route("analyze_tax")

    events = audit.events()
    assert [e.event_type for e in events] == ["task", "result"]
    assert audit.verify() is True


def test_route_without_audit_log_does_not_error():
    core = NexusCore()  # audit=None
    agent = Agent(name="A", capabilities=["x"])

    @agent.task("op")
    def handler(task: Task) -> dict:
        return {"ok": True}

    core.register(agent)
    result_envelope = core.route("op")
    assert result_envelope["payload"]["output"]["ok"] is True


def _register_good_and_bad_agents(core: NexusCore) -> None:
    """`bad` is registered first (so first-match would pick it) but only
    ever produces low-quality evidence; `good` produces high-quality
    evidence. Both handle "shared_op" identically otherwise."""
    bad = Agent(name="Bad", capabilities=["shared_op", "warm_up_bad"])
    good = Agent(name="Good", capabilities=["shared_op", "warm_up_good"])

    @bad.task("warm_up_bad")
    def warm_bad(task: Task) -> Result:
        ev = bad.make_evidence(claim="x", source="y", transformation="inferred", confidence=0.5)
        return Result(task_id=task.id, status="success", output={}, evidence=[ev])

    @good.task("warm_up_good")
    def warm_good(task: Task) -> Result:
        ev = good.make_evidence(claim="x", source="y", transformation="extracted_verbatim", confidence=0.95)
        return Result(task_id=task.id, status="success", output={}, evidence=[ev])

    @bad.task("shared_op")
    def handle_bad(task: Task) -> dict:
        return {"handled_by": "bad"}

    @good.task("shared_op")
    def handle_good(task: Task) -> dict:
        return {"handled_by": "good"}

    core.register(bad)
    core.register(good)
    core.route("warm_up_bad")
    core.route("warm_up_good")


def test_route_with_trust_evaluator_prefers_higher_scoring_agent():
    core = NexusCore(trust=TrustEvaluator())
    _register_good_and_bad_agents(core)

    result_envelope = core.route("shared_op")
    assert result_envelope["payload"]["output"]["handled_by"] == "good"


def test_route_without_trust_evaluator_keeps_first_match_regardless_of_evidence():
    core = NexusCore()  # trust=None — RFC-0004: unchanged behavior
    _register_good_and_bad_agents(core)

    result_envelope = core.route("shared_op")
    assert result_envelope["payload"]["output"]["handled_by"] == "bad"
