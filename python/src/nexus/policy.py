"""Level 8 (Policy + Security) — implements RFC-0006: gates a task's
execution based on its self-declared `risk` level (RFC-0001 §4 / RFC-0003
§3's `nexus.risk` metadata), per ARCHITECTURE.md principle 5: "Any action
with real-world side effects... follows: plan -> simulate -> assess risk ->
approve -> execute -> audit. Critical-risk actions require human approval by
default."

This module implements the assess-risk / approve / execute / audit half of
that pipeline — not `plan` or `simulate`, which would need agents to expose
a dry-run capability this project does not have yet (RFC-0006 Open
Questions). It also does not enforce `task.constraints` — that needs
adapters to declare what they touch (network, cost, filesystem), which does
not exist yet either.

Fails closed: a task whose risk requires approval, with no approver
configured, is blocked, not allowed through — "human approval by default"
means the absence of an approval mechanism is equivalent to approval
withheld, not equivalent to approval granted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .protocol import Task

PolicyAction = Literal["allow", "block", "require_approval"]

DEFAULT_RISK_POLICY: dict[str | None, PolicyAction] = {
    None: "allow",
    "low": "allow",
    "medium": "allow",
    "high": "require_approval",
    "critical": "require_approval",
}

Approver = Callable[[Task, "PolicyDecision"], bool]


@dataclass
class PolicyDecision:
    action: PolicyAction
    reason: str
    risk: str | None


class PolicyEngine:
    def __init__(
        self,
        risk_policy: dict[str | None, PolicyAction] | None = None,
        approver: Approver | None = None,
    ) -> None:
        self.risk_policy = dict(risk_policy if risk_policy is not None else DEFAULT_RISK_POLICY)
        self.approver = approver

    def evaluate(self, task: Task) -> PolicyDecision:
        # Task.risk is a closed set at the protocol layer (RFC-0001 §4) —
        # this default matters for a *custom* risk_policy that forgot to
        # map one of the valid values, not for a value nobody defined the
        # meaning of. Either way, missing means require-approval, not
        # allow: an unmapped risk level is not evidence of safety.
        action = self.risk_policy.get(task.risk, "require_approval")

        if action == "allow":
            return PolicyDecision(action="allow", reason=f"risk={task.risk!r} is within policy", risk=task.risk)

        if action == "require_approval":
            if self.approver is None:
                return PolicyDecision(
                    action="block",
                    reason=f"risk={task.risk!r} requires approval, but no approver is configured (fails closed)",
                    risk=task.risk,
                )
            pending = PolicyDecision(action="require_approval", reason="pending approval", risk=task.risk)
            if self.approver(task, pending):
                return PolicyDecision(action="allow", reason=f"risk={task.risk!r} approved", risk=task.risk)
            return PolicyDecision(action="block", reason=f"risk={task.risk!r} approval denied", risk=task.risk)

        return PolicyDecision(action="block", reason=f"risk={task.risk!r} is blocked by policy", risk=task.risk)
