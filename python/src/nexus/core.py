"""Nexus Core — the minimal Level 2 router/orchestrator/agent registry.

This is a single-process, in-memory reference implementation: it exists to
prove the RFC-0001/RFC-0002 wire format round-trips through something
runnable, and to give Levels 6/7 (trust-informed selection, arbitration) a
seam to plug into later. It intentionally does not:

- talk to a real transport (MCP, HTTP, a queue) — see RFC-0001's transport
  bindings open question,
- do capability-based routing beyond "first agent with a matching handler" —
  real selection (cost, trust, load) is Level 6 (Evidence + Trust),
- enforce `task.constraints` / `task.risk` — that is Level 8 (Policy + Security).

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
from .protocol import ErrorPayload, ProtocolError, Result, Task, envelope, validate_envelope

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


class NexusCore:
    def __init__(self, graph: GraphSink | None = None) -> None:
        self._agents: dict[str, Agent] = {}
        self.trace: list[dict[str, Any]] = []
        self.graph = graph

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
        self.trace.append(task_envelope)

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
            self.trace.append(error_envelope)
            return error_envelope

        agent = candidates[0]  # Level 6 will replace this with real selection.
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
        self.trace.append(result_envelope)
        return result_envelope
