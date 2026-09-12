"""Level 6 (Evidence + Trust) — implements RFC-0004: a trust score derived
from an agent's historical Evidence (RFC-0001 §5), never self-reported
(ARCHITECTURE.md principle 4; RFC-0002 deliberately has no self-reported
`trust` field for the same reason).

This is deliberately a narrow, provisional signal: it answers "does this
agent's own evidence-production look careful?" — self-reported confidence
weighted by how strong the `transformation` type is, minus a penalty for
any attributed lessons-learned recurrences. It has no way yet to know
whether a piece of evidence was later contradicted or corroborated by
another agent; that signal is Level 7's job (Debate + Arbitration, not yet
designed) to produce. See RFC-0004 for the full reasoning and the explicit
seam left for Level 7 to plug into.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .protocol import Evidence

TRANSFORMATION_WEIGHTS = {
    "extracted_verbatim": 1.0,
    "computed": 0.9,
    "summarized": 0.7,
    "inferred": 0.5,
}

RECURRENCE_PENALTY_PER_LESSON = 0.05
MAX_RECURRENCE_PENALTY = 0.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class TrustScore:
    agent_id: str
    score: float
    sample_size: int
    evaluated_at: str = field(default_factory=_now_iso)
    breakdown: dict[str, Any] = field(default_factory=dict)


class TrustEvaluator:
    def __init__(self, transformation_weights: dict[str, float] | None = None) -> None:
        self.transformation_weights = dict(transformation_weights or TRANSFORMATION_WEIGHTS)

    def _weighted_confidence(self, evidence: Evidence) -> float:
        weight = self.transformation_weights.get(evidence.transformation, 0.5)
        return evidence.confidence * weight

    def evaluate(self, agent_id: str, evidence: list[Evidence], recurrences: int = 0) -> TrustScore:
        """RFC-0004 §2-3: `evidence` may contain entries from any agent —
        only those attributed to `agent_id` are scored."""
        own_evidence = [e for e in evidence if e.agent_id == agent_id]
        if not own_evidence:
            return TrustScore(
                agent_id=agent_id, score=0.0, sample_size=0,
                breakdown={"reason": "no evidence on file"},
            )

        weighted = [self._weighted_confidence(e) for e in own_evidence]
        raw_score = sum(weighted) / len(weighted)
        penalty = min(MAX_RECURRENCE_PENALTY, recurrences * RECURRENCE_PENALTY_PER_LESSON)
        score = max(0.0, min(1.0, raw_score - penalty))

        return TrustScore(
            agent_id=agent_id,
            score=score,
            sample_size=len(own_evidence),
            breakdown={
                "raw_score": raw_score,
                "recurrence_penalty": penalty,
                "avg_confidence": sum(e.confidence for e in own_evidence) / len(own_evidence),
            },
        )

    def rank(self, agent_ids: list[str], evidence: list[Evidence]) -> list[TrustScore]:
        scores = [self.evaluate(agent_id, evidence) for agent_id in agent_ids]
        return sorted(scores, key=lambda s: s.score, reverse=True)
