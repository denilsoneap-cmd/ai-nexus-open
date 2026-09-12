import pytest

from nexus.arbitration import ArbitrationEngine, Candidate
from nexus.protocol import Evidence, Result
from nexus.trust import TrustEvaluator


def make_evidence(agent_id: str, transformation: str, confidence: float) -> Evidence:
    return Evidence(claim="x", source="y", agent_id=agent_id, transformation=transformation, confidence=confidence)


def test_single_candidate_wins_by_default():
    engine = ArbitrationEngine()
    candidate = Candidate("agent:a", Result(task_id="t1", output={"answer": 42}))
    verdict = engine.arbitrate("t1", [candidate])
    assert verdict.winner_agent_id == "agent:a"
    assert verdict.agreement is True
    assert "only one candidate" in verdict.reasoning


def test_identical_outputs_are_treated_as_agreement():
    engine = ArbitrationEngine()
    a = Candidate("agent:a", Result(task_id="t1", output={"answer": 42}))
    b = Candidate("agent:b", Result(task_id="t1", output={"answer": 42}))
    verdict = engine.arbitrate("t1", [a, b])
    assert verdict.agreement is True
    assert verdict.winner_agent_id == "agent:a"  # first in order, since they agree


def test_disagreement_is_won_by_stronger_evidence_not_by_which_came_first():
    engine = ArbitrationEngine()
    weak = Candidate(
        "agent:weak",
        Result(task_id="t1", output={"answer": "wrong"},
               evidence=[make_evidence("agent:weak", "inferred", 0.6)]),
    )
    strong = Candidate(
        "agent:strong",
        Result(task_id="t1", output={"answer": "right"},
               evidence=[make_evidence("agent:strong", "extracted_verbatim", 0.95)]),
    )
    # weak listed FIRST — if this won just by order, the test would catch it
    verdict = engine.arbitrate("t1", [weak, strong])
    assert verdict.winner_agent_id == "agent:strong"
    assert verdict.agreement is False
    assert "evidence strength" in verdict.reasoning


def test_disagreement_with_no_evidence_anywhere_keeps_first_candidate_order():
    engine = ArbitrationEngine()
    a = Candidate("agent:a", Result(task_id="t1", output={"answer": "a"}))
    b = Candidate("agent:b", Result(task_id="t1", output={"answer": "b"}))
    verdict = engine.arbitrate("t1", [a, b])
    assert verdict.winner_agent_id == "agent:a"


def test_evidence_strength_tie_breaks_on_historical_trust():
    engine = ArbitrationEngine(TrustEvaluator())
    a = Candidate("agent:a", Result(task_id="t1", output={"answer": "a"},
                                     evidence=[make_evidence("agent:a", "computed", 0.8)]))
    b = Candidate("agent:b", Result(task_id="t1", output={"answer": "b"},
                                     evidence=[make_evidence("agent:b", "computed", 0.8)]))
    # identical evidence strength on this decision — but agent:b has a much
    # stronger historical track record
    historical = [
        make_evidence("agent:a", "inferred", 0.3),
        make_evidence("agent:b", "extracted_verbatim", 0.99),
    ]
    verdict = engine.arbitrate("t1", [a, b], historical_evidence=historical)
    assert verdict.winner_agent_id == "agent:b"
    assert "historical trust" in verdict.reasoning


def test_verdict_candidates_report_every_candidate_not_just_winner():
    engine = ArbitrationEngine()
    a = Candidate("agent:a", Result(task_id="t1", output={"answer": "a"}))
    b = Candidate("agent:b", Result(task_id="t1", output={"answer": "b"},
                                     evidence=[make_evidence("agent:b", "extracted_verbatim", 0.9)]))
    verdict = engine.arbitrate("t1", [a, b])
    assert len(verdict.candidates) == 2
    assert {c["agent_id"] for c in verdict.candidates} == {"agent:a", "agent:b"}


def test_arbitrate_rejects_empty_candidate_list():
    engine = ArbitrationEngine()
    with pytest.raises(ValueError):
        engine.arbitrate("t1", [])


def test_many_agree_does_not_outvote_one_with_strong_evidence():
    """The exact scenario ARCHITECTURE.md principle 3 names: three agents
    confidently repeating an unsupported claim vs. one with real evidence."""
    engine = ArbitrationEngine()
    crowd = [
        Candidate(f"agent:crowd{i}", Result(task_id="t1", output={"answer": "popular"}))
        for i in range(3)
    ]
    lone = Candidate(
        "agent:lone",
        Result(task_id="t1", output={"answer": "correct"},
               evidence=[make_evidence("agent:lone", "extracted_verbatim", 0.99)]),
    )
    verdict = engine.arbitrate("t1", [*crowd, lone])
    assert verdict.winner_agent_id == "agent:lone"
