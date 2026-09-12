from nexus.policy import PolicyEngine
from nexus.protocol import Task


def make_task(risk: str | None) -> Task:
    return Task(id="t1", objective="op", risk=risk)


def test_low_and_medium_risk_are_allowed_by_default():
    engine = PolicyEngine()
    assert engine.evaluate(make_task("low")).action == "allow"
    assert engine.evaluate(make_task("medium")).action == "allow"


def test_no_declared_risk_is_allowed_by_default():
    engine = PolicyEngine()
    assert engine.evaluate(make_task(None)).action == "allow"


def test_high_and_critical_risk_are_blocked_with_no_approver_configured():
    """PolicyEngine() with no approver fails closed: the risk_policy map
    says "require_approval" for high/critical, but evaluate()'s final
    decision — with nothing able to grant that approval — is "block", not
    "require_approval" left dangling."""
    engine = PolicyEngine()
    assert engine.evaluate(make_task("high")).action == "block"
    assert engine.evaluate(make_task("critical")).action == "block"


def test_fails_closed_when_approval_required_but_no_approver_configured():
    """RFC-0006 §3: no approver means no approval is possible, which means
    blocked — the default PolicyEngine (no approver) must never let a
    critical task through."""
    engine = PolicyEngine()
    decision = engine.evaluate(make_task("critical"))
    assert decision.action == "block"
    assert "no approver" in decision.reason


def test_approver_granting_approval_allows_the_task():
    engine = PolicyEngine(approver=lambda task, decision: True)
    decision = engine.evaluate(make_task("critical"))
    assert decision.action == "allow"
    assert "approved" in decision.reason


def test_approver_denying_approval_blocks_the_task():
    engine = PolicyEngine(approver=lambda task, decision: False)
    decision = engine.evaluate(make_task("critical"))
    assert decision.action == "block"
    assert "denied" in decision.reason


def test_approver_receives_the_task_and_pending_decision():
    seen = {}

    def approver(task: Task, decision) -> bool:
        seen["task_id"] = task.id
        seen["risk"] = decision.risk
        return True

    engine = PolicyEngine(approver=approver)
    engine.evaluate(make_task("high"))
    assert seen == {"task_id": "t1", "risk": "high"}


def test_incomplete_custom_policy_requires_approval_not_allow():
    """Task.risk is a closed set at the protocol layer (RFC-0001 §4:
    low/medium/high/critical or None) — an agent cannot invent a novel risk
    string. What this guards against instead is a deployment's *own*
    risk_policy configuration missing an entry (e.g. forgot to map "low"):
    the missing entry must default to needing approval, not to allow."""
    engine = PolicyEngine(risk_policy={None: "allow"})  # "low" deliberately left unmapped
    decision = engine.evaluate(make_task("low"))
    assert decision.action == "block"  # requires approval, none configured, fails closed


def test_custom_risk_policy_can_hard_block_a_risk_level():
    engine = PolicyEngine(risk_policy={None: "allow", "critical": "block"})
    decision = engine.evaluate(make_task("critical"))
    assert decision.action == "block"
    assert "blocked by policy" in decision.reason


def test_custom_risk_policy_can_relax_defaults():
    engine = PolicyEngine(risk_policy={None: "allow", "critical": "allow"})
    assert engine.evaluate(make_task("critical")).action == "allow"
