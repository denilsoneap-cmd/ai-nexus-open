from nexus.arbitration import Verdict
from nexus.conflict_policy import ConflictPolicy
from nexus.protocol import Result


def make_verdict(agreement: bool, reasoning: str = "some reasoning") -> Verdict:
    return Verdict(
        task_id="t1", winner_agent_id="agent:a",
        winning_result=Result(task_id="t1", output={}),
        agreement=agreement, reasoning=reasoning,
    )


def test_agreement_is_allowed_with_no_policy_configured():
    policy = ConflictPolicy()
    decision = policy.evaluate(make_verdict(agreement=True))
    assert decision.action == "allow"
    assert decision.agreement is True


def test_disagreement_is_blocked_with_no_approver_configured():
    """Fails closed, same as PolicyEngine: an unreviewed disagreement
    between candidates must never pass through silently just because the
    arbitration math still picked a winner."""
    policy = ConflictPolicy()
    decision = policy.evaluate(make_verdict(agreement=False))
    assert decision.action == "block"
    assert "no approver" in decision.reason


def test_approver_granting_approval_allows_a_disagreement():
    policy = ConflictPolicy(approver=lambda verdict, decision: True)
    decision = policy.evaluate(make_verdict(agreement=False))
    assert decision.action == "allow"
    assert "approved" in decision.reason


def test_approver_denying_approval_blocks_a_disagreement():
    policy = ConflictPolicy(approver=lambda verdict, decision: False)
    decision = policy.evaluate(make_verdict(agreement=False))
    assert decision.action == "block"
    assert "denied" in decision.reason


def test_approver_is_not_consulted_when_candidates_agreed():
    calls = []
    policy = ConflictPolicy(approver=lambda verdict, decision: calls.append(1) or True)
    policy.evaluate(make_verdict(agreement=True))
    assert calls == []


def test_approver_receives_the_verdict_and_pending_decision():
    seen = {}

    def approver(verdict: Verdict, decision) -> bool:
        seen["task_id"] = verdict.task_id
        seen["pending_agreement"] = decision.agreement
        return True

    policy = ConflictPolicy(approver=approver)
    policy.evaluate(make_verdict(agreement=False, reasoning="3 candidates disagreed"))
    assert seen == {"task_id": "t1", "pending_agreement": False}


def test_block_reason_includes_the_verdicts_own_reasoning():
    policy = ConflictPolicy()
    decision = policy.evaluate(make_verdict(agreement=False, reasoning="2 candidates disagreed, x won"))
    assert "2 candidates disagreed, x won" in decision.reason
