"""Agent SDK — the developer-facing surface described in the top-level README.

    from nexus import Agent

    agent = Agent(name="Tax Specialist", capabilities=["tax_analysis"])

    @agent.task("analyze_tax")
    def analyze(task):
        ...

A handler receives the :class:`~nexus.protocol.Task` and may return either a
plain ``dict`` (wrapped into a successful :class:`~nexus.protocol.Result`) or
a :class:`~nexus.protocol.Result` directly for full control over status,
confidence, and evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .identity import AgentIdentity
from .protocol import ErrorPayload, Evidence, ProtocolError, Result, Task

Handler = Callable[[Task], "Result | dict[str, Any] | ErrorPayload"]


class CapabilityUnavailable(LookupError):
    """No handler is registered for the requested objective."""


class TaskFailed(Exception):
    """A registered handler ran but could not complete the task — carries
    the ErrorPayload it returned (RFC-0001 §4.2), as opposed to
    CapabilityUnavailable, which means no handler existed at all."""

    def __init__(self, error: ErrorPayload) -> None:
        self.error = error
        super().__init__(error.message)


class Agent:
    def __init__(
        self,
        name: str,
        capabilities: list[str] | None = None,
        role: str | None = None,
        scope: str = "project",
        agent_id: str | None = None,
    ) -> None:
        self.identity = AgentIdentity(
            agent_id=agent_id or AgentIdentity().agent_id,
            name=name,
            role=role or name,
            capabilities=list(capabilities or []),
            scope=scope,
        )
        self._handlers: dict[str, Handler] = {}

    def task(self, objective: str) -> Callable[[Handler], Handler]:
        """Decorator registering `fn` as the handler for `objective`."""

        def decorator(fn: Handler) -> Handler:
            self._handlers[objective] = fn
            return fn

        return decorator

    def objectives(self) -> list[str]:
        return list(self._handlers)

    def handle(self, incoming: Task) -> Result:
        """Run the registered handler for `incoming.objective` and normalize
        its return value into a :class:`Result`. Raises `CapabilityUnavailable`
        if no handler is registered — the caller (NexusCore) is responsible
        for turning that into an `error` envelope (RFC-0001 §4.2)."""
        handler = self._handlers.get(incoming.objective)
        if handler is None:
            raise CapabilityUnavailable(
                f"{self.identity.agent_id} has no handler for objective "
                f"{incoming.objective!r}"
            )
        outcome = handler(incoming)
        if isinstance(outcome, Result):
            if outcome.task_id != incoming.id:
                raise ProtocolError(
                    f"handler returned Result for task_id={outcome.task_id!r}, "
                    f"expected {incoming.id!r}"
                )
            return outcome
        if isinstance(outcome, ErrorPayload):
            raise TaskFailed(outcome)
        if isinstance(outcome, dict):
            return Result(task_id=incoming.id, status="success", output=outcome)
        raise ProtocolError(
            f"handler for {incoming.objective!r} must return a dict, Result, or "
            f"ErrorPayload, got {type(outcome).__name__}"
        )

    def make_evidence(
        self,
        claim: str,
        source: str,
        transformation: str,
        confidence: float,
        location: str | None = None,
    ) -> Evidence:
        """Convenience for handlers building §5 Evidence attributed to self."""
        return Evidence(
            claim=claim,
            source=source,
            agent_id=self.identity.agent_id,
            transformation=transformation,
            confidence=confidence,
            location=location,
        )

    def refuse(self, incoming: Task, reason: str) -> Result:
        return Result(task_id=incoming.id, status="refused", output={"reason": reason})

    def fail(self, incoming: Task, error_code: str, message: str, retryable: bool = False) -> ErrorPayload:
        return ErrorPayload(task_id=incoming.id, error_code=error_code, message=message, retryable=retryable)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Agent({self.identity.name!r}, agent_id={self.identity.agent_id!r})"
