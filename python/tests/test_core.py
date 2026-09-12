import pytest

from nexus.adapters.graph import GraphStore
from nexus.agent import Agent, CapabilityUnavailable
from nexus.arbitration import ArbitrationEngine
from nexus.audit import AuditLog
from nexus.core import NexusCore
from nexus.policy import PolicyEngine
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


def test_route_with_lessons_penalizes_agent_with_recurring_lessons(tmp_path):
    """RFC-0004's previously-open lesson-to-agent link: two agents would
    otherwise tie on evidence strength, but one of them has a recurring
    lesson on file — NexusCore(trust=..., lessons=...) should look that up
    automatically and prefer the other agent, without the caller passing
    any recurrence count by hand."""
    from nexus.adapters.lessons import LessonStore

    lessons = LessonStore(tmp_path)
    core = NexusCore(trust=TrustEvaluator(), lessons=lessons)

    flaky = Agent(name="Flaky", capabilities=["shared_op", "warm_up_flaky"])
    steady = Agent(name="Steady", capabilities=["shared_op", "warm_up_steady"])

    @flaky.task("warm_up_flaky")
    def warm_flaky(task: Task) -> Result:
        ev = flaky.make_evidence(claim="x", source="y", transformation="extracted_verbatim", confidence=0.9)
        return Result(task_id=task.id, status="success", output={}, evidence=[ev])

    @steady.task("warm_up_steady")
    def warm_steady(task: Task) -> Result:
        ev = steady.make_evidence(claim="x", source="y", transformation="extracted_verbatim", confidence=0.9)
        return Result(task_id=task.id, status="success", output={}, evidence=[ev])

    @flaky.task("shared_op")
    def handle_flaky(task: Task) -> dict:
        return {"handled_by": "flaky"}

    @steady.task("shared_op")
    def handle_steady(task: Task) -> dict:
        return {"handled_by": "steady"}

    core.register(flaky)
    core.register(steady)
    core.route("warm_up_flaky")
    core.route("warm_up_steady")

    # Identical evidence quality so far — first-match order would pick "flaky".
    assert core.route("shared_op")["payload"]["output"]["handled_by"] == "flaky"

    lessons.record(symptom="Flaky broke prod", correction="Added a hook", agent_id=flaky.identity.agent_id)
    lessons.record(symptom="Flaky broke prod", correction="Hardened the hook", agent_id=flaky.identity.agent_id)

    assert core.route("shared_op")["payload"]["output"]["handled_by"] == "steady"


def test_route_with_trust_but_without_lessons_ignores_recurrences():
    core = NexusCore(trust=TrustEvaluator())  # lessons=None — unaffected by this feature
    _register_good_and_bad_agents(core)
    result_envelope = core.route("shared_op")
    assert result_envelope["payload"]["output"]["handled_by"] == "good"


def test_debate_requires_an_arbiter():
    core = NexusCore()  # arbiter=None
    agent = Agent(name="A", capabilities=["op"])

    @agent.task("op")
    def handler(task: Task) -> dict:
        return {"ok": True}

    core.register(agent)
    with pytest.raises(RuntimeError):
        core.debate("op")


def test_debate_fans_out_to_every_capable_agent_and_arbitrates():
    core = NexusCore(arbiter=ArbitrationEngine())

    weak = Agent(name="Weak", capabilities=["classify"])
    strong = Agent(name="Strong", capabilities=["classify"])

    @weak.task("classify")
    def weak_handle(task: Task) -> Result:
        ev = weak.make_evidence(claim="x", source="y", transformation="inferred", confidence=0.5)
        return Result(task_id=task.id, output={"label": "spam"}, evidence=[ev])

    @strong.task("classify")
    def strong_handle(task: Task) -> Result:
        ev = strong.make_evidence(claim="x", source="y", transformation="extracted_verbatim", confidence=0.95)
        return Result(task_id=task.id, output={"label": "ham"}, evidence=[ev])

    core.register(weak)
    core.register(strong)

    verdict = core.debate("classify")
    assert verdict.winner_agent_id == strong.identity.agent_id
    assert len(verdict.candidates) == 2


def test_debate_drops_agents_whose_handler_fails():
    """Exercises debate()'s `except (CapabilityUnavailable, TaskFailed):
    continue` — a partial debate among agents that actually answered beats
    failing the whole thing because one candidate errored."""
    core = NexusCore(arbiter=ArbitrationEngine())
    good = Agent(name="Good", capabilities=["classify"])
    failing = Agent(name="Failing", capabilities=["classify"])

    @good.task("classify")
    def good_handle(task: Task) -> dict:
        return {"label": "ok"}

    @failing.task("classify")
    def failing_handle(task: Task):
        return failing.fail(task, error_code="boom", message="handler broke")

    core.register(good)
    core.register(failing)

    verdict = core.debate("classify")
    assert len(verdict.candidates) == 1
    assert verdict.winner_agent_id == good.identity.agent_id


def test_debate_raises_when_no_agent_registered_for_objective():
    core = NexusCore(arbiter=ArbitrationEngine())
    with pytest.raises(CapabilityUnavailable):
        core.debate("nonexistent_objective")


def test_debate_can_target_a_subset_of_agents_by_id():
    core = NexusCore(arbiter=ArbitrationEngine())
    a = Agent(name="A", capabilities=["op"])
    b = Agent(name="B", capabilities=["op"])

    @a.task("op")
    def handle_a(task: Task) -> dict:
        return {"handled_by": "a"}

    @b.task("op")
    def handle_b(task: Task) -> dict:
        return {"handled_by": "b"}

    core.register(a)
    core.register(b)

    verdict = core.debate("op", agent_ids=[a.identity.agent_id])
    assert len(verdict.candidates) == 1
    assert verdict.winner_agent_id == a.identity.agent_id


def _register_simple_agent(core: NexusCore, objective: str = "op") -> Agent:
    agent = Agent(name="A", capabilities=[objective])

    @agent.task(objective)
    def handler(task: Task) -> dict:
        return {"ok": True}

    core.register(agent)
    return agent


def test_route_without_policy_ignores_risk_entirely():
    core = NexusCore()  # policy=None — unaffected by this RFC
    _register_simple_agent(core)
    result_envelope = core.route("op", risk="critical")
    assert result_envelope["message_type"] == "result"


def test_route_blocks_critical_risk_task_with_no_approver():
    core = NexusCore(policy=PolicyEngine())
    _register_simple_agent(core)
    result_envelope = core.route("op", risk="critical")
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "policy_blocked"


def test_route_allows_low_risk_task_through_policy():
    core = NexusCore(policy=PolicyEngine())
    _register_simple_agent(core)
    result_envelope = core.route("op", risk="low")
    assert result_envelope["message_type"] == "result"


def test_route_with_approver_allows_critical_risk_task():
    core = NexusCore(policy=PolicyEngine(approver=lambda task, decision: True))
    _register_simple_agent(core)
    result_envelope = core.route("op", risk="critical")
    assert result_envelope["message_type"] == "result"


def test_blocked_task_still_appears_in_trace_and_audit():
    audit = AuditLog()
    core = NexusCore(policy=PolicyEngine(), audit=audit)
    _register_simple_agent(core)
    core.route("op", risk="critical")

    assert [e["message_type"] for e in core.trace] == ["task", "error"]
    assert [e.event_type for e in audit.events()] == ["task", "error"]
    assert audit.verify() is True


def test_policy_blocked_task_never_reaches_the_agent():
    core = NexusCore(policy=PolicyEngine())
    calls = []
    agent = Agent(name="A", capabilities=["op"])

    @agent.task("op")
    def handler(task: Task) -> dict:
        calls.append(task.id)
        return {"ok": True}

    core.register(agent)
    core.route("op", risk="critical")
    assert calls == []


def test_debate_is_gated_by_policy_same_as_route():
    """Regression: debate() used to ignore self.policy entirely — a caller
    could bypass route()'s risk-based approval gate just by calling
    debate() instead, for the exact same objective."""
    core = NexusCore(arbiter=ArbitrationEngine(), policy=PolicyEngine())  # no approver — fails closed
    _register_simple_agent(core)
    with pytest.raises(PermissionError):
        core.debate("op", risk="critical")


def test_debate_proceeds_when_policy_approves():
    core = NexusCore(
        arbiter=ArbitrationEngine(),
        policy=PolicyEngine(approver=lambda task, decision: True),
    )
    _register_simple_agent(core)
    verdict = core.debate("op", risk="critical")
    assert verdict.winner_agent_id is not None


def test_debate_parallel_matches_sequential_arbitration():
    """Same scenario as test_debate_fans_out_to_every_capable_agent_and_arbitrates,
    run with parallel=True — the winner and candidate count must not depend
    on execution order."""
    core = NexusCore(arbiter=ArbitrationEngine())

    weak = Agent(name="Weak", capabilities=["classify"])
    strong = Agent(name="Strong", capabilities=["classify"])

    @weak.task("classify")
    def weak_handle(task: Task) -> Result:
        ev = weak.make_evidence(claim="x", source="y", transformation="inferred", confidence=0.5)
        return Result(task_id=task.id, output={"label": "spam"}, evidence=[ev])

    @strong.task("classify")
    def strong_handle(task: Task) -> Result:
        ev = strong.make_evidence(claim="x", source="y", transformation="extracted_verbatim", confidence=0.95)
        return Result(task_id=task.id, output={"label": "ham"}, evidence=[ev])

    core.register(weak)
    core.register(strong)

    verdict = core.debate("classify", parallel=True)
    assert verdict.winner_agent_id == strong.identity.agent_id
    assert len(verdict.candidates) == 2


def test_debate_parallel_actually_overlaps_in_wall_time():
    """Proves parallel=True dispatches concurrently rather than just
    accepting the flag and running sequentially anyway: three handlers each
    sleep 0.2s: sequential would take >=0.6s, concurrent should take well
    under that."""
    import time

    core = NexusCore(arbiter=ArbitrationEngine())
    for label in ("a", "b", "c"):
        agent = Agent(name=label, capabilities=["slow_op"])

        def handler(task: Task, _label: str = label) -> dict:
            time.sleep(0.2)
            return {"handled_by": _label}

        agent.task("slow_op")(handler)
        core.register(agent)

    started = time.monotonic()
    verdict = core.debate("slow_op", parallel=True)
    elapsed = time.monotonic() - started

    assert len(verdict.candidates) == 3
    assert elapsed < 0.5  # well under 3 * 0.2s if actually concurrent


def test_debate_parallel_drops_agents_whose_handler_fails():
    core = NexusCore(arbiter=ArbitrationEngine())
    good = Agent(name="Good", capabilities=["classify"])
    failing = Agent(name="Failing", capabilities=["classify"])

    @good.task("classify")
    def good_handle(task: Task) -> dict:
        return {"label": "ok"}

    @failing.task("classify")
    def failing_handle(task: Task):
        return failing.fail(task, error_code="boom", message="handler broke")

    core.register(good)
    core.register(failing)

    verdict = core.debate("classify", parallel=True)
    assert len(verdict.candidates) == 1
    assert verdict.winner_agent_id == good.identity.agent_id


def test_debate_parallel_records_trace_audit_and_graph_in_pool_order():
    """Recorded order/edges must be identical to the sequential path even
    though handlers complete out of order — the "Strong" agent is
    registered second but finishes first; graph/candidates order must
    still follow registration (pool) order, not completion order."""
    import time

    graph = GraphStore()
    audit = AuditLog()
    core = NexusCore(arbiter=ArbitrationEngine(), graph=graph, audit=audit)

    slow_first = Agent(name="SlowFirst", capabilities=["classify"])
    fast_second = Agent(name="FastSecond", capabilities=["classify"])

    @slow_first.task("classify")
    def slow_handle(task: Task) -> dict:
        time.sleep(0.1)
        return {"label": "slow"}

    @fast_second.task("classify")
    def fast_handle(task: Task) -> dict:
        return {"label": "fast"}

    core.register(slow_first)
    core.register(fast_second)

    verdict = core.debate("classify", task_id="task-parallel-order", parallel=True)

    assert [c["agent_id"] for c in verdict.candidates] == [
        slow_first.identity.agent_id, fast_second.identity.agent_id,
    ]
    task_node = "task:task-parallel-order"
    routed_to_order = [e["target_id"] for e in graph.edges_from(task_node) if e["relation"] == "routed_to"]
    assert routed_to_order == [slow_first.identity.agent_id, fast_second.identity.agent_id]
    assert [e["message_type"] for e in core.trace] == ["task", "result"]
    assert audit.verify() is True


def test_debate_without_policy_configured_ignores_risk():
    core = NexusCore(arbiter=ArbitrationEngine())  # policy=None
    _register_simple_agent(core)
    verdict = core.debate("op", risk="critical")  # should not raise
    assert verdict.winner_agent_id is not None


def test_debate_records_task_and_result_in_trace():
    core = NexusCore(arbiter=ArbitrationEngine())
    agent = _register_simple_agent(core)
    verdict = core.debate("op")

    assert [e["message_type"] for e in core.trace] == ["task", "result"]
    assert core.trace[1]["sender"]["agent_id"] == agent.identity.agent_id
    assert core.trace[1]["correlation_id"] == core.trace[0]["message_id"]
    assert core.trace[1]["payload"]["output"] == verdict.winning_result.output


def test_debate_with_audit_log_records_task_and_result_events():
    audit = AuditLog()
    core = NexusCore(arbiter=ArbitrationEngine(), audit=audit)
    _register_simple_agent(core)
    core.debate("op")

    events = audit.events()
    assert [e.event_type for e in events] == ["task", "result"]
    assert audit.verify() is True


def test_debate_blocked_by_policy_appears_in_trace_before_raising():
    audit = AuditLog()
    core = NexusCore(arbiter=ArbitrationEngine(), policy=PolicyEngine(), audit=audit)
    _register_simple_agent(core)

    with pytest.raises(PermissionError):
        core.debate("op", risk="critical")

    assert [e["message_type"] for e in core.trace] == ["task", "error"]
    assert core.trace[1]["payload"]["error_code"] == "policy_blocked"
    assert [e.event_type for e in audit.events()] == ["task", "error"]


def test_debate_no_agent_registered_appears_in_trace_before_raising():
    core = NexusCore(arbiter=ArbitrationEngine())
    with pytest.raises(CapabilityUnavailable):
        core.debate("nonexistent_objective")

    assert [e["message_type"] for e in core.trace] == ["task", "error"]
    assert core.trace[1]["payload"]["error_code"] == "capability_unavailable"


def test_debate_no_usable_candidate_appears_in_trace_before_raising():
    core = NexusCore(arbiter=ArbitrationEngine())
    failing = Agent(name="Failing", capabilities=["classify"])

    @failing.task("classify")
    def failing_handle(task: Task):
        return failing.fail(task, error_code="boom", message="handler broke")

    core.register(failing)

    with pytest.raises(RuntimeError):
        core.debate("classify")

    assert [e["message_type"] for e in core.trace] == ["task", "error"]
    assert core.trace[1]["payload"]["error_code"] == "no_usable_candidate"


def _register_slow_and_fast_agents(core: NexusCore) -> tuple[Agent, Agent]:
    import time

    slow = Agent(name="Slow", capabilities=["classify"])
    fast = Agent(name="Fast", capabilities=["classify"])

    @slow.task("classify")
    def slow_handle(task: Task) -> dict:
        time.sleep(0.3)
        return {"handled_by": "slow"}

    @fast.task("classify")
    def fast_handle(task: Task) -> dict:
        return {"handled_by": "fast"}

    core.register(slow)
    core.register(fast)
    return slow, fast


def test_debate_max_candidates_caps_the_pool_in_registration_order():
    core = NexusCore(arbiter=ArbitrationEngine())
    a = Agent(name="A", capabilities=["op"])
    b = Agent(name="B", capabilities=["op"])

    @a.task("op")
    def handle_a(task: Task) -> dict:
        return {"handled_by": "a"}

    @b.task("op")
    def handle_b(task: Task) -> dict:
        return {"handled_by": "b"}

    core.register(a)
    core.register(b)

    verdict = core.debate("op", max_candidates=1)
    assert len(verdict.candidates) == 1
    assert verdict.candidates[0]["agent_id"] == a.identity.agent_id


def test_debate_without_max_candidates_uses_every_registered_agent():
    core = NexusCore(arbiter=ArbitrationEngine())
    agent_a = Agent(name="X", capabilities=["op"])
    agent_b = Agent(name="Y", capabilities=["op"])

    @agent_a.task("op")
    def handle_a(task: Task) -> dict:
        return {"handled_by": "x"}

    @agent_b.task("op")
    def handle_b(task: Task) -> dict:
        return {"handled_by": "y"}

    core.register(agent_a)
    core.register(agent_b)

    verdict = core.debate("op")
    assert len(verdict.candidates) == 2


def test_debate_timeout_drops_a_candidate_that_takes_too_long():
    core = NexusCore(arbiter=ArbitrationEngine())
    slow, fast = _register_slow_and_fast_agents(core)

    verdict = core.debate("classify", timeout=0.05)
    assert len(verdict.candidates) == 1
    assert verdict.winner_agent_id == fast.identity.agent_id


def test_debate_timeout_applies_in_parallel_mode_too():
    core = NexusCore(arbiter=ArbitrationEngine())
    slow, fast = _register_slow_and_fast_agents(core)

    verdict = core.debate("classify", timeout=0.05, parallel=True)
    assert len(verdict.candidates) == 1
    assert verdict.winner_agent_id == fast.identity.agent_id


def test_debate_without_timeout_lets_slow_candidates_finish():
    core = NexusCore(arbiter=ArbitrationEngine())
    slow, fast = _register_slow_and_fast_agents(core)

    verdict = core.debate("classify")  # timeout=None, default
    assert len(verdict.candidates) == 2


def test_debate_quorum_not_met_raises_and_appears_in_trace():
    core = NexusCore(arbiter=ArbitrationEngine())
    good = Agent(name="Good", capabilities=["classify"])
    failing = Agent(name="Failing", capabilities=["classify"])

    @good.task("classify")
    def good_handle(task: Task) -> dict:
        return {"ok": True}

    @failing.task("classify")
    def failing_handle(task: Task):
        return failing.fail(task, error_code="boom", message="handler broke")

    core.register(good)
    core.register(failing)

    with pytest.raises(RuntimeError):
        core.debate("classify", quorum=2)  # only 1 of 2 will actually respond

    assert [e["message_type"] for e in core.trace] == ["task", "error"]
    assert core.trace[1]["payload"]["error_code"] == "quorum_not_met"


def test_debate_quorum_met_arbitrates_normally():
    core = NexusCore(arbiter=ArbitrationEngine())
    a = Agent(name="A", capabilities=["op"])
    b = Agent(name="B", capabilities=["op"])

    @a.task("op")
    def handle_a(task: Task) -> dict:
        return {"handled_by": "a"}

    @b.task("op")
    def handle_b(task: Task) -> dict:
        return {"handled_by": "b"}

    core.register(a)
    core.register(b)

    verdict = core.debate("op", quorum=2)
    assert len(verdict.candidates) == 2


def test_debate_without_quorum_arbitrates_with_however_many_responded():
    core = NexusCore(arbiter=ArbitrationEngine())
    good = Agent(name="Good", capabilities=["classify"])
    failing = Agent(name="Failing", capabilities=["classify"])

    @good.task("classify")
    def good_handle(task: Task) -> dict:
        return {"ok": True}

    @failing.task("classify")
    def failing_handle(task: Task):
        return failing.fail(task, error_code="boom", message="handler broke")

    core.register(good)
    core.register(failing)

    verdict = core.debate("classify")  # quorum=None, default
    assert len(verdict.candidates) == 1
