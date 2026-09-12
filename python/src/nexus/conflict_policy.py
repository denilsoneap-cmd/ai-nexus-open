"""Level 8-adjacent (Policy + Security), for Level 7's arbitration
(RFC-0005) rather than RFC-0006's risk gating: `ArbitrationEngine` always
picks a winner, even when candidates disagreed — `Verdict.agreement`
already says whether they did, but nothing acts on it. `ConflictPolicy` is
the optional gate on top, the same "assess -> approve -> execute" shape
`nexus.policy.PolicyEngine` already uses for self-declared risk, applied
here to *evidence disagreement* instead.

Fails closed, same reasoning as `PolicyEngine`: a disagreement with no
`approver` configured blocks by default, not passes silently — an
unreviewed 3-way split between candidate models is not evidence the
winner is trustworthy just because the arbitration math picked one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .arbitration import Verdict

ConflictAction = Literal["allow", "block"]


@dataclass
class ConflictDecision:
    action: ConflictAction
    reason: str
    agreement: bool


ConflictApprover = Callable[["Verdict", ConflictDecision], bool]


class ConflictPolicy:
    def __init__(self, approver: ConflictApprover | None = None) -> None:
        self.approver = approver

    def evaluate(self, verdict: "Verdict") -> ConflictDecision:
        if verdict.agreement:
            return ConflictDecision(action="allow", reason="candidates agreed", agreement=True)

        if self.approver is None:
            return ConflictDecision(
                action="block",
                reason=f"candidates disagreed ({verdict.reasoning}) and no approver is configured (fails closed)",
                agreement=False,
            )

        pending = ConflictDecision(action="block", reason="pending approval", agreement=False)
        if self.approver(verdict, pending):
            return ConflictDecision(action="allow", reason=f"disagreement approved: {verdict.reasoning}", agreement=False)
        return ConflictDecision(action="block", reason=f"disagreement approval denied: {verdict.reasoning}", agreement=False)
