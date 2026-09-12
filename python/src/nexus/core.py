"""Nexus Core — the minimal Level 2 router/orchestrator/agent registry.

This is a single-process, in-memory reference implementation: it exists to
prove the RFC-0001/RFC-0002 wire format round-trips through something
runnable. It intentionally does not:

- talk to a real transport (MCP, HTTP, a queue) — see RFC-0001's transport
  bindings open question,
- do capability-based routing beyond "first agent with a matching handler,"
  unless a `trust` evaluator is supplied (RFC-0004, `nexus.trust`) — even
  then, selection only weighs evidence quality, not cost or load, which
  remain open,
- enforce `task.constraints` — that remains open (RFC-0006 §1); `task.risk`
  is now gated when a `policy` engine is supplied (RFC-0006, `nexus.policy`).

Every envelope that passes through `route()` is recorded in `self.trace` in
send order, which is the seed of Level 9 (Execution + Observability): a full
task trace today is just "read this list."

See [ARCHITECTURE.md](../../../ARCHITECTURE.md#layer-breakdown) for the
distinction between these ROADMAP.md build-sequence Levels and the L0N
module-ownership layers — they are different numbering schemes.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from .agent import Agent, CapabilityUnavailable, TaskFailed
from .arbitration import Candidate, Verdict
from .protocol import ErrorPayload, Evidence, Task, envelope, validate_envelope

CORE_SENDER = {"agent_id": "agent:" + "0" * 32}  # reserved id for the orchestrator itself


class GraphSink(Protocol):
    """Structural type for an optional Level 12 graph store. `NexusCore`
    depends on this shape, not on `nexus.adapters.graph.GraphStore`
    concretely — any object with this method works (per ARCHITECTURE.md
    principle 1, the core does not import adapters)."""

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...


class AuditSink(Protocol):
    """Structural type for an optional Level 9 audit log (see `nexus.audit`).
    Same reasoning as `GraphSink`: a shape, not a concrete import."""

    def append(self, event_type: str, actor: str, payload: dict[str, Any]) -> Any: ...


class TrustSource(Protocol):
    """Structural type for an optional Level 6 trust evaluator (RFC-0004,
    see `nexus.trust.TrustEvaluator`). Same reasoning as `GraphSink`: a
    shape (`.evaluate(...)` returning something with a `.score`), not a
    concrete import of `nexus.trust`."""

    def evaluate(self, agent_id: str, evidence: list[Evidence], recurrences: int = 0) -> Any: ...


class ArbitrationSource(Protocol):
    """Structural type for an optional Level 7 arbitration engine (RFC-0005,
    see `nexus.arbitration.ArbitrationEngine`). Same reasoning as `GraphSink`."""

    def arbitrate(
        self, task_id: str, candidates: list[Candidate], historical_evidence: list[Evidence] | None = None,
    ) -> Verdict: ...


class PolicySource(Protocol):
    """Structural type for an optional Level 8 policy engine (RFC-0006,
    see `nexus.policy.PolicyEngine`). Same reasoning as `GraphSink`."""

    def evaluate(self, task: Task) -> Any: ...


class NexusCore:
    def __init__(
        self,
        graph: GraphSink | None = None,
        audit: AuditSink | None = None,
        trust: TrustSource | None = None,
        arbiter: ArbitrationSource | None = None,
        policy: PolicySource | None = None,
    ) -> None:
        self._agents: dict[str, Agent] = {}
        self.trace: list[dict[str, Any]] = []
        self.graph = graph
        self.audit = audit
        self.trust = trust
        self.arbiter = arbiter
        self.policy = policy

    def _record(self, env: dict[str, Any]) -> None:
        self.trace.append(env)
        if self.audit is not None:
            self.audit.append(event_type=env["message_type"], actor=env["sender"]["agent_id"], payload=env)

    def _historical_evidence(self) -> list[Evidence]:
        """RFC-0004 §4: the evidence pool a trust score is computed from —
        every Evidence entry attached to a `result` envelope recorded so far."""
        pool: list[Evidence] = []
        for env in self.trace:
            if env.get("message_type") != "result":
                continue
            for e in env["payload"].get("evidence", []):
                pool.append(Evidence.from_dict(e))
        return pool

    def register(self, agent: Agent) -> None:
        self._agents[agent.identity.agent_id] = agent

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    def agents(self) -> list[Agent]:
        return list(self._agents.values())

    def find_by_capability(self, capability: str) -> list[Agent]:
        """RFC-0002 §2: match on declared `capabilities`, not `role`."""
        return [a for a in self._agents.values() if capability in a.identity.capabilities]

    def find_by_objective(self, objective: str) -> list[Agent]:
        """Agents with a registered handler for this exact objective."""
        return [a for a in self._agents.values() if objective in a.objectives()]

    def route(
        self,
        objective: str,
        input: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
        risk: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a task for `objective` to the first capable agent and return
        the resulting `result` or `error` envelope (RFC-0001 §4.1/§4.2)."""
        task = Task(
            id=task_id or f"task-{uuid.uuid4().hex[:8]}",
            objective=objective,
            input=input or {},
            constraints=constraints or [],
            risk=risk,
        )
        task_envelope = envelope(
            message_type="task",
            sender=CORE_SENDER,
            payload=task.to_payload(),
        )
        validate_envelope(task_envelope)
        self._record(task_envelope)

        if self.policy is not None:
            decision = self.policy.evaluate(task)
            if decision.action != "allow":
                err = ErrorPayload(
                    task_id=task.id,
                    error_code="policy_blocked",
                    message=decision.reason,
                    retryable=False,
                )
                policy_envelope = envelope(
                    message_type="error",
                    sender=CORE_SENDER,
                    payload=err.to_payload(),
                    correlation_id=task_envelope["message_id"],
                )
                validate_envelope(policy_envelope)
                self._record(policy_envelope)
                return policy_envelope

        candidates = self.find_by_objective(objective)
        if not candidates:
            err = ErrorPayload(
                task_id=task.id,
                error_code="capability_unavailable",
                message=f"No agent registered with a handler for objective {objective!r}.",
                retryable=False,
            )
            error_envelope = envelope(
                message_type="error",
                sender=CORE_SENDER,
                payload=err.to_payload(),
                correlation_id=task_envelope["message_id"],
            )
            validate_envelope(error_envelope)
            self._record(error_envelope)
            return error_envelope

        agent = candidates[0]
        if self.trust is not None and len(candidates) > 1:
            # RFC-0004 §4: pick the highest-trust candidate; ties (including
            # the common all-zero-evidence case) keep first-match order, so
            # behavior with no trust evaluator configured, or no evidence
            # on file yet, is unchanged from before this RFC.
            evidence_pool = self._historical_evidence()
            best_score = -1.0
            for candidate in candidates:
                score = self.trust.evaluate(candidate.identity.agent_id, evidence_pool).score
                if score > best_score:
                    best_score = score
                    agent = candidate
        task_node = f"task:{task.id}"
        if self.graph is not None:
            self.graph.add_edge(task_node, agent.identity.agent_id, "routed_to")

        try:
            result = agent.handle(task)
        except CapabilityUnavailable as exc:  # pragma: no cover - defensive
            err = ErrorPayload(task_id=task.id, error_code="capability_unavailable", message=str(exc))
            result_envelope = envelope(
                message_type="error",
                sender=agent.identity.to_dict(minimal=True),
                payload=err.to_payload(),
                correlation_id=task_envelope["message_id"],
            )
        except TaskFailed as exc:
            result_envelope = envelope(
                message_type="error",
                sender=agent.identity.to_dict(minimal=True),
                payload=exc.error.to_payload(),
                correlation_id=task_envelope["message_id"],
            )
        else:
            result_envelope = envelope(
                message_type="result",
                sender=agent.identity.to_dict(minimal=True),
                payload=result.to_payload(),
                correlation_id=task_envelope["message_id"],
            )
            if self.graph is not None:
                self.graph.add_edge(
                    agent.identity.agent_id, task_node, "produced_result",
                    confidence=result.confidence if result.confidence is not None else 1.0,
                )
                for ev in result.evidence:
                    evidence_node = f"evidence:{uuid.uuid4().hex[:12]}"
                    self.graph.add_edge(
                        task_node, evidence_node, "supported_by",
                        confidence=ev.confidence,
                        metadata={"claim": ev.claim, "source": ev.source, "agent_id": ev.agent_id},
                    )
        validate_envelope(result_envelope)
        self._record(result_envelope)
        return result_envelope

    def debate(
        self,
        objective: str,
        input: dict[str, Any] | None = None,
        agent_ids: list[str] | None = None,
        task_id: str | None = None,
        risk: str | None = None,
    ) -> Verdict:
        """RFC-0005: send the same task to every agent capable of
        `objective` (or the subset named by `agent_ids`) and arbitrate their
        results. Requires `NexusCore(arbiter=...)` — unlike `route()`,
        there is no sane default for "no arbiter provided."

        `risk` is gated by `self.policy` (RFC-0006) exactly like `route()`'s
        — without this, a caller could bypass risk-based approval entirely
        just by using `debate()` instead of `route()` for the same
        objective, which would have quietly undermined RFC-0006's whole
        guarantee. Raises `PermissionError` on a non-"allow" decision,
        since `Verdict` (unlike `route()`'s envelope) has no "blocked" shape
        to return instead.

        Now records into `trace`/`audit`/`graph` the same way `route()`
        does (RFC-0005 §5's previous known limitation): the task envelope
        first, a `routed_to` edge per candidate actually dispatched to, a
        `produced_result`/`supported_by` edge for each one that answered,
        and finally a `result` envelope for the arbitrated winner — or an
        `error` envelope (recorded before the corresponding exception is
        raised) for a policy block, no registered agent, or no usable
        candidate, mirroring `route()`'s error paths."""
        if self.arbiter is None:
            raise RuntimeError("NexusCore.debate() requires an arbiter — see NexusCore(arbiter=...)")

        task = Task(id=task_id or f"task-{uuid.uuid4().hex[:8]}", objective=objective, input=input or {}, risk=risk)
        task_envelope = envelope(message_type="task", sender=CORE_SENDER, payload=task.to_payload())
        validate_envelope(task_envelope)
        self._record(task_envelope)

        def _record_error(error_code: str, message: str) -> None:
            err = ErrorPayload(task_id=task.id, error_code=error_code, message=message, retryable=False)
            error_envelope = envelope(
                message_type="error", sender=CORE_SENDER, payload=err.to_payload(),
                correlation_id=task_envelope["message_id"],
            )
            validate_envelope(error_envelope)
            self._record(error_envelope)

        if self.policy is not None:
            decision = self.policy.evaluate(task)
            if decision.action != "allow":
                _record_error("policy_blocked", decision.reason)
                raise PermissionError(f"debate() blocked by policy: {decision.reason}")

        pool = self.find_by_objective(objective)
        if agent_ids is not None:
            pool = [a for a in pool if a.identity.agent_id in agent_ids]
        if not pool:
            message = f"No agent registered with a handler for objective {objective!r}."
            _record_error("capability_unavailable", message)
            raise CapabilityUnavailable(f"no agent registered with a handler for objective {objective!r}")

        task_node = f"task:{task.id}"
        candidates: list[Candidate] = []
        for candidate_agent in pool:
            if self.graph is not None:
                self.graph.add_edge(task_node, candidate_agent.identity.agent_id, "routed_to")
            try:
                result = candidate_agent.handle(task)
            except (CapabilityUnavailable, TaskFailed):
                continue  # a partial debate among agents that answered beats none at all
            candidates.append(Candidate(agent_id=candidate_agent.identity.agent_id, result=result))
            if self.graph is not None:
                self.graph.add_edge(
                    candidate_agent.identity.agent_id, task_node, "produced_result",
                    confidence=result.confidence if result.confidence is not None else 1.0,
                )
                for ev in result.evidence:
                    evidence_node = f"evidence:{uuid.uuid4().hex[:12]}"
                    self.graph.add_edge(
                        task_node, evidence_node, "supported_by",
                        confidence=ev.confidence,
                        metadata={"claim": ev.claim, "source": ev.source, "agent_id": ev.agent_id},
                    )

        if not candidates:
            message = f"no candidate produced a usable result for objective {objective!r}"
            _record_error("no_usable_candidate", message)
            raise RuntimeError(message)

        verdict = self.arbiter.arbitrate(task.id, candidates, self._historical_evidence())

        winner = next(a for a in pool if a.identity.agent_id == verdict.winner_agent_id)
        result_envelope = envelope(
            message_type="result", sender=winner.identity.to_dict(minimal=True),
            payload=verdict.winning_result.to_payload(),
            correlation_id=task_envelope["message_id"],
        )
        validate_envelope(result_envelope)
        self._record(result_envelope)

        return verdict
