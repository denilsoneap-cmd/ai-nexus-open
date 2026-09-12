"""Level 7 (Debate + Arbitration) — implements RFC-0005: reconciling
multiple agents' results for the same task.

ARCHITECTURE.md principle 3: "the system does not average or vote by
default... The Arbitration Engine looks for the argument with the strongest
evidence, not the most votes." This module is that engine: given several
(agent_id, Result) pairs answering the same task, it does not count how many
agents agree — it compares how strong each result's own attached evidence is
(`nexus.trust.evidence_strength`, the same formula RFC-0004 uses for
historical trust, applied here per-decision instead), and falls back to
historical trust only on an exact tie, never as the primary signal — an
agent's history should not decide the answer to a single question the
evidence itself already makes clear.

Does not attempt to determine whether two different-looking `output` dicts
actually mean the same thing — only byte-for-byte equality counts as
agreement (see RFC-0005 §2 for why this is a deliberate limitation, not an
oversight).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .protocol import Result
from .trust import TrustEvaluator, evidence_strength


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Candidate:
    agent_id: str
    result: Result


@dataclass
class Verdict:
    task_id: str
    winner_agent_id: str
    winning_result: Result
    agreement: bool
    reasoning: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    decided_at: str = field(default_factory=_now_iso)


class ArbitrationEngine:
    def __init__(self, trust_evaluator: TrustEvaluator | None = None) -> None:
        self.trust_evaluator = trust_evaluator or TrustEvaluator()

    def _describe(self, candidate: Candidate, historical_evidence: list[Any] | None) -> dict[str, Any]:
        own_strength = evidence_strength(candidate.result.evidence, self.trust_evaluator.transformation_weights)
        trust_score = 0.0
        if historical_evidence:
            trust_score = self.trust_evaluator.evaluate(candidate.agent_id, historical_evidence).score
        return {
            "agent_id": candidate.agent_id,
            "output": candidate.result.output,
            "evidence_strength": own_strength,
            "trust_score": trust_score,
        }

    def arbitrate(
        self,
        task_id: str,
        candidates: list[Candidate],
        historical_evidence: list[Any] | None = None,
    ) -> Verdict:
        if not candidates:
            raise ValueError("arbitrate() needs at least one candidate")

        descriptions = [self._describe(c, historical_evidence) for c in candidates]

        if len(candidates) == 1:
            only = candidates[0]
            return Verdict(
                task_id=task_id, winner_agent_id=only.agent_id, winning_result=only.result,
                agreement=True, reasoning="only one candidate responded",
                candidates=descriptions,
            )

        outputs = [c.result.output for c in candidates]
        if all(o == outputs[0] for o in outputs):
            winner = candidates[0]
            return Verdict(
                task_id=task_id, winner_agent_id=winner.agent_id, winning_result=winner.result,
                agreement=True,
                reasoning=f"all {len(candidates)} candidates produced the same output",
                candidates=descriptions,
            )

        # RFC-0005 §3: evidence strength wins; historical trust only breaks
        # an exact tie; a further tie keeps first-candidate order
        # deterministically (max() returns the first maximal element).
        winner, winner_desc = max(
            zip(candidates, descriptions, strict=True),
            key=lambda pair: (pair[1]["evidence_strength"], pair[1]["trust_score"]),
        )
        tied_on_evidence = [d for d in descriptions if d["evidence_strength"] == winner_desc["evidence_strength"]]
        if len(tied_on_evidence) > 1:
            reasoning = (
                f"{len(candidates)} candidates disagreed; tied on evidence strength "
                f"({winner_desc['evidence_strength']:.2f}), {winner.agent_id} won on "
                f"historical trust ({winner_desc['trust_score']:.2f})"
            )
        else:
            reasoning = (
                f"{len(candidates)} candidates disagreed; {winner.agent_id} won on "
                f"evidence strength ({winner_desc['evidence_strength']:.2f})"
            )

        return Verdict(
            task_id=task_id, winner_agent_id=winner.agent_id, winning_result=winner.result,
            agreement=False, reasoning=reasoning, candidates=descriptions,
        )
