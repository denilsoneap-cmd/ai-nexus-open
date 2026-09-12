import pytest

from nexus.protocol import Evidence
from nexus.trust import TrustEvaluator, TrustScore


def make_evidence(agent_id: str, transformation: str, confidence: float) -> Evidence:
    return Evidence(
        claim="x", source="y", agent_id=agent_id,
        transformation=transformation, confidence=confidence,
    )


def test_agent_with_no_evidence_scores_zero():
    evaluator = TrustEvaluator()
    score = evaluator.evaluate("agent:a", evidence=[])
    assert score.score == 0.0
    assert score.sample_size == 0


def test_extracted_verbatim_outweighs_inferred_at_equal_confidence():
    evaluator = TrustEvaluator()
    verbatim = evaluator.evaluate("agent:a", [make_evidence("agent:a", "extracted_verbatim", 0.9)])
    inferred = evaluator.evaluate("agent:a", [make_evidence("agent:a", "inferred", 0.9)])
    assert verbatim.score > inferred.score


def test_only_evidence_attributed_to_agent_is_counted():
    evaluator = TrustEvaluator()
    evidence = [
        make_evidence("agent:a", "extracted_verbatim", 0.9),
        make_evidence("agent:b", "extracted_verbatim", 0.1),
    ]
    score = evaluator.evaluate("agent:a", evidence)
    assert score.sample_size == 1


def test_score_is_clamped_to_one():
    evaluator = TrustEvaluator()
    score = evaluator.evaluate("agent:a", [make_evidence("agent:a", "extracted_verbatim", 1.0)])
    assert score.score <= 1.0


def test_recurrence_penalty_reduces_score():
    evaluator = TrustEvaluator()
    evidence = [make_evidence("agent:a", "extracted_verbatim", 0.9)]
    clean = evaluator.evaluate("agent:a", evidence, recurrences=0)
    penalized = evaluator.evaluate("agent:a", evidence, recurrences=3)
    assert penalized.score < clean.score
    assert penalized.breakdown["recurrence_penalty"] == pytest.approx(0.15)


def test_recurrence_penalty_is_capped():
    evaluator = TrustEvaluator()
    evidence = [make_evidence("agent:a", "extracted_verbatim", 0.9)]
    score = evaluator.evaluate("agent:a", evidence, recurrences=100)
    assert score.breakdown["recurrence_penalty"] == 0.5
    assert score.score >= 0.0


def test_breakdown_is_transparent():
    evaluator = TrustEvaluator()
    score = evaluator.evaluate("agent:a", [make_evidence("agent:a", "computed", 0.8)])
    assert "raw_score" in score.breakdown
    assert "avg_confidence" in score.breakdown


def test_rank_orders_agents_by_score_descending():
    evaluator = TrustEvaluator()
    evidence = [
        make_evidence("agent:a", "inferred", 0.6),
        make_evidence("agent:b", "extracted_verbatim", 0.99),
    ]
    ranked = evaluator.rank(["agent:a", "agent:b"], evidence)
    assert [r.agent_id for r in ranked] == ["agent:b", "agent:a"]


def test_custom_transformation_weights_are_honored():
    evaluator = TrustEvaluator(transformation_weights={"inferred": 1.0, "extracted_verbatim": 0.1})
    inferred = evaluator.evaluate("agent:a", [make_evidence("agent:a", "inferred", 0.9)])
    verbatim = evaluator.evaluate("agent:a", [make_evidence("agent:a", "extracted_verbatim", 0.9)])
    assert inferred.score > verbatim.score


def test_trust_score_is_a_dataclass_with_expected_fields():
    score = TrustScore(agent_id="agent:a", score=0.5, sample_size=1)
    assert score.agent_id == "agent:a"
    assert score.evaluated_at  # auto-populated
