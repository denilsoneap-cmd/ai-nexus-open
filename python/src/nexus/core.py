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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Protocol

from .agent import Agent, CapabilityUnavailable, TaskFailed
from .arbitration import Candidate, Verdict
from .conflict_policy import ConflictBlocked
from .protocol import ErrorPayload, Evidence, Result, Task, envelope, validate_envelope

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


class LessonSource(Protocol):
    """Structural type for an optional Level 5 lessons store (see
    `nexus.adapters.lessons.LessonStore`). Same reasoning as `GraphSink`.
    Closes RFC-0004's previously-open lesson-to-agent link: when supplied
    alongside `trust`, `route()` looks up each candidate's own recurrence
    count instead of the caller having to already know and pass it."""

    def recurrences_for(self, agent_id: str) -> int: ...


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


class ConflictPolicySource(Protocol):
    """Structural type for an optional arbitration-disagreement gate (see
    `nexus.conflict_policy.ConflictPolicy`) — distinct from `PolicySource`:
    that one gates a task's self-declared `risk` before dispatch, this one
    gates `debate()`'s `Verdict.agreement` after arbitration. Same
    reasoning as `GraphSink`."""

    def evaluate(self, verdict: Verdict) -> Any: ...


class NexusCore:
    def __init__(
        self,
        graph: GraphSink | None = None,
        audit: AuditSink | None = None,
        trust: TrustSource | None = None,
        arbiter: ArbitrationSource | None = None,
        policy: PolicySource | None = None,
        lessons: LessonSource | None = None,
        conflict_policy: ConflictPolicySource | None = None,
    ) -> None:
        self._agents: dict[str, Agent] = {}
        self.trace: list[dict[str, Any]] = []
        self.graph = graph
        self.audit = audit
        self.trust = trust
        self.arbiter = arbiter
        self.policy = policy
        self.lessons = lessons
        self.conflict_policy = conflict_policy

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
                recurrences = (
                    self.lessons.recurrences_for(candidate.identity.agent_id)
                    if self.lessons is not None else 0
                )
                score = self.trust.evaluate(candidate.identity.agent_id, evidence_pool, recurrences).score
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

    @staticmethod
    def _call_with_timeout(candidate_agent: Agent, task: Task, timeout: float | None) -> Result:
        """Plain direct call when `timeout` is `None` (the default) —
        zero behavior/overhead change from before timeouts existed. A
        timeout is enforced by running the handler in its own thread and
        giving up waiting after `timeout` seconds; Python cannot forcibly
        kill a thread, so a handler that ignores the timeout keeps running
        in the background even though `debate()` has moved on — same
        caveat `parallel=True` already carries about handlers needing to
        behave themselves."""
        if timeout is None:
            return candidate_agent.handle(task)
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(candidate_agent.handle, task).result(timeout=timeout)

    @classmethod
    def _dispatch_candidates_sequential(
        cls, pool: list[Agent], task: Task, timeout: float | None = None,
    ) -> dict[str, Result]:
        results: dict[str, Result] = {}
        for candidate_agent in pool:
            try:
                results[candidate_agent.identity.agent_id] = cls._call_with_timeout(candidate_agent, task, timeout)
            except (CapabilityUnavailable, TaskFailed, FutureTimeoutError):
                pass  # a partial debate among agents that answered beats none at all
        return results

    @staticmethod
    def _dispatch_candidates_parallel(
        pool: list[Agent], task: Task, timeout: float | None = None,
    ) -> dict[str, Result]:
        results: dict[str, Result] = {}
        with ThreadPoolExecutor(max_workers=len(pool)) as executor:
            future_to_agent = {executor.submit(candidate_agent.handle, task): candidate_agent for candidate_agent in pool}
            for future in future_to_agent:
                candidate_agent = future_to_agent[future]
                try:
                    results[candidate_agent.identity.agent_id] = future.result(timeout=timeout)
                except (CapabilityUnavailable, TaskFailed, FutureTimeoutError):
                    pass
        return results

    def debate(
        self,
        objective: str,
        input: dict[str, Any] | None = None,
        agent_ids: list[str] | None = None,
        task_id: str | None = None,
        risk: str | None = None,
        parallel: bool = False,
        timeout: float | None = None,
        quorum: int | None = None,
        max_candidates: int | None = None,
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

        Records into `trace`/`audit`/`graph` the same way `route()` does:
        the task envelope first, a `routed_to` edge per candidate actually
        dispatched to, a `produced_result`/`supported_by` edge for each one
        that answered, and finally a `result` envelope for the arbitrated
        winner — or an `error` envelope (recorded before the corresponding
        exception is raised) for a policy block, no registered agent, or no
        usable candidate, mirroring `route()`'s error paths.

        `parallel=False` (default) calls each candidate's `handle()`
        sequentially, in `pool` order — unchanged since RFC-0005. With
        `parallel=True`, every candidate's `handle()` runs concurrently in
        its own thread (a `ThreadPoolExecutor`, sized to the candidate
        count); only the actual handler calls are concurrent — the
        trace/audit/graph bookkeeping below still happens afterward, in a
        single thread, in the original `pool` order, so recorded order and
        the arbitrated outcome are identical either way (see
        `test_debate_parallel_matches_sequential_arbitration`). This makes
        `parallel=True` safe only for handlers that don't share mutable
        state with each other — the same precondition any concurrent task
        runner has.

        RFC-0005 §5's remaining known gaps, all opt-in and all `None`/off
        by default (unchanged behavior unless asked for):
        - `max_candidates` caps how many of `pool` actually get dispatched
          (first `max_candidates`, in `pool`/registration order) — bounds
          cost/wall-time when many agents are capable of `objective` but
          debating all of them isn't worth it.
        - `timeout` (seconds) bounds how long any single candidate's
          `handle()` gets before being treated as a non-response (dropped,
          same as a `TaskFailed`/`CapabilityUnavailable` candidate) —
          Python cannot forcibly kill a thread, so a handler that ignores
          this keeps running in the background regardless.
        - `quorum` requires at least that many candidates to have actually
          responded before arbitrating at all; fewer raises `RuntimeError`
          (`error_code="quorum_not_met"`, recorded the same way the
          existing "no candidate responded at all" error is) instead of
          arbitrating a decision from a thinner pool than the caller
          considered meaningful.

        `self.conflict_policy` (`NexusCore(conflict_policy=...)`, see
        `nexus.conflict_policy.ConflictPolicy`), if configured, gates the
        arbitrated `Verdict` itself, after `self.arbiter.arbitrate()` has
        already run: candidates agreeing lets the verdict through as
        normal; candidates *disagreeing* (`verdict.agreement is False`) —
        an unreviewed evidence conflict between models — raises
        `nexus.conflict_policy.ConflictBlocked` (a `PermissionError`
        subclass carrying the blocked `.verdict`, so a caller can still
        inspect `.verdict.candidates` — e.g. to release per-candidate
        resources it allocated for this debate) with
        `error_code="conflict_not_approved"` recorded the same way a
        `self.policy` block already is, unless the configured approver
        accepts it. This is a different axis from
        `self.policy`/`risk`: that gates a task's self-declared risk
        *before* any candidate runs; this gates *disagreement among the
        results* after they all have."""
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
        if max_candidates is not None:
            pool = pool[:max_candidates]

        task_node = f"task:{task.id}"
        results_by_agent_id = (
            self._dispatch_candidates_parallel(pool, task, timeout) if parallel
            else self._dispatch_candidates_sequential(pool, task, timeout)
        )

        candidates: list[Candidate] = []
        for candidate_agent in pool:
            if self.graph is not None:
                self.graph.add_edge(task_node, candidate_agent.identity.agent_id, "routed_to")
            result = results_by_agent_id.get(candidate_agent.identity.agent_id)
            if result is None:
                continue  # this candidate's handle() raised CapabilityUnavailable/TaskFailed
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
        if quorum is not None and len(candidates) < quorum:
            message = (
                f"only {len(candidates)} of required quorum {quorum} candidates produced a "
                f"usable result for objective {objective!r}"
            )
            _record_error("quorum_not_met", message)
            raise RuntimeError(message)

        verdict = self.arbiter.arbitrate(task.id, candidates, self._historical_evidence())

        if self.conflict_policy is not None:
            decision = self.conflict_policy.evaluate(verdict)
            if decision.action != "allow":
                _record_error("conflict_not_approved", decision.reason)
                raise ConflictBlocked(verdict, f"debate() blocked by conflict policy: {decision.reason}")

        winner = next(a for a in pool if a.identity.agent_id == verdict.winner_agent_id)
        if self.graph is not None:
            # routed_to/produced_result are recorded per-candidate above,
            # but nothing yet marks which one actually won — without this
            # edge, a caller reading the graph back (not the in-memory,
            # per-run-only trace) has no way to tell a winner from a loser.
            self.graph.add_edge(task_node, winner.identity.agent_id, "won")
        result_envelope = envelope(
            message_type="result", sender=winner.identity.to_dict(minimal=True),
            payload=verdict.winning_result.to_payload(),
            correlation_id=task_envelope["message_id"],
        )
        validate_envelope(result_envelope)
        self._record(result_envelope)

        return verdict
