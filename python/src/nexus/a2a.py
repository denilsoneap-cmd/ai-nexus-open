"""A2A alignment layer — implements RFC-0003, which supersedes RFC-0001 and
RFC-0002. Translates between Nexus's domain objects (Task, Result,
ErrorPayload, Evidence, AgentIdentity — still useful as typed, validated
Python objects) and the wire shapes defined by the Agent2Agent (A2A)
Protocol (a2a-protocol.org).

This module does not implement an A2A transport (JSON-RPC/gRPC/HTTP server
or client) — that is real future work (ROADMAP.md Level 2, "message bus").
It implements the *shape* mapping precisely enough to round-trip Nexus's
existing objects through A2A's Message/Task/Artifact/AgentCard model, which
is what RFC-0003 needed proven, not a full networked implementation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .identity import AgentIdentity
from .protocol import ErrorPayload, Evidence, ProtocolError, Result, Task

NEXUS_EVIDENCE_EXTENSION = "https://ai-nexus-open.org/extensions/evidence/v1"

TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELED", "REJECTED"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_message_id() -> str:
    return f"msg-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Identity -> AgentCard (RFC-0003 §2)
# ---------------------------------------------------------------------------


def to_agent_card(identity: AgentIdentity) -> dict[str, Any]:
    card: dict[str, Any] = {
        "id": identity.agent_id,
        "provider": {"name": identity.name or identity.agent_id},
        "skills": [{"name": cap} for cap in identity.capabilities],
        "extensions": [NEXUS_EVIDENCE_EXTENSION],
        "metadata": {"scope": identity.scope},
    }
    if identity.role is not None:
        card["metadata"]["role"] = identity.role
    if identity.model is not None:
        card["metadata"]["model"] = identity.model
    return card


def agent_card_to_identity(card: dict[str, Any]) -> AgentIdentity:
    metadata = card.get("metadata", {})
    return AgentIdentity(
        agent_id=card["id"],
        name=card.get("provider", {}).get("name"),
        role=metadata.get("role"),
        capabilities=[s["name"] for s in card.get("skills", [])],
        scope=metadata.get("scope", "project"),
        model=metadata.get("model"),
    )


# ---------------------------------------------------------------------------
# Task -> A2A Message (RFC-0003 §3)
# ---------------------------------------------------------------------------


def task_to_a2a_message(task: Task, context_id: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"nexus.objective": task.objective}
    if task.constraints:
        metadata["nexus.constraints"] = task.constraints
    if task.risk is not None:
        metadata["nexus.risk"] = task.risk
    if task.deadline is not None:
        metadata["nexus.deadline"] = task.deadline
    if task.context:
        metadata["nexus.context"] = task.context

    message: dict[str, Any] = {
        "messageId": _new_message_id(),
        "taskId": task.id,
        "role": "agent",
        "parts": [{"structuredData": task.input}] if task.input else [],
        "metadata": metadata,
    }
    if context_id is not None:
        message["contextId"] = context_id
    return message


def a2a_message_to_task(message: dict[str, Any]) -> Task:
    metadata = message.get("metadata", {})
    if "nexus.objective" not in metadata:
        raise ProtocolError("A2A message missing required 'nexus.objective' metadata")

    input_data: dict[str, Any] = {}
    for part in message.get("parts", []):
        if "structuredData" in part:
            input_data = part["structuredData"]
            break

    return Task(
        id=message.get("taskId") or f"task-{uuid.uuid4().hex[:8]}",
        objective=metadata["nexus.objective"],
        input=input_data,
        constraints=metadata.get("nexus.constraints", []),
        risk=metadata.get("nexus.risk"),
        deadline=metadata.get("nexus.deadline"),
        context=metadata.get("nexus.context", {}),
    )


# ---------------------------------------------------------------------------
# Evidence -> A2A Artifact, under the Nexus evidence extension (RFC-0003 §4)
# ---------------------------------------------------------------------------


def evidence_to_artifact(evidence: Evidence) -> dict[str, Any]:
    return {
        "id": f"artifact-{uuid.uuid4().hex[:8]}",
        "mediaType": "application/json",
        "extension": NEXUS_EVIDENCE_EXTENSION,
        "parts": [{"structuredData": evidence.to_dict()}],
    }


def artifact_to_evidence(artifact: dict[str, Any]) -> Evidence:
    if artifact.get("extension") != NEXUS_EVIDENCE_EXTENSION:
        raise ProtocolError(
            f"artifact is not a Nexus evidence extension artifact: {artifact.get('extension')!r}"
        )
    for part in artifact.get("parts", []):
        if "structuredData" in part:
            return Evidence.from_dict(part["structuredData"])
    raise ProtocolError("evidence artifact has no structuredData part")


# ---------------------------------------------------------------------------
# Result / ErrorPayload <-> A2A Task (RFC-0003 §3/§5)
# ---------------------------------------------------------------------------


def result_to_a2a_task(result: Result, context_id: str | None = None) -> dict[str, Any]:
    output_artifact = {
        "id": f"artifact-{uuid.uuid4().hex[:8]}",
        "mediaType": "application/json",
        "parts": [{"structuredData": result.output}],
    }
    artifacts = [output_artifact] + [evidence_to_artifact(e) for e in result.evidence]

    state = {"success": "COMPLETED", "partial": "COMPLETED", "refused": "REJECTED"}[result.status]
    task: dict[str, Any] = {
        "id": result.task_id,
        "status": {"state": state, "timestamp": _now_iso()},
        "artifacts": artifacts,
        "metadata": {"nexus.status": result.status},
    }
    if result.confidence is not None:
        task["metadata"]["nexus.confidence"] = result.confidence
    if context_id is not None:
        task["contextId"] = context_id
    return task


def error_to_a2a_task(error: ErrorPayload, context_id: str | None = None) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": error.task_id,
        "status": {
            "state": "FAILED",
            "message": error.message,
            "timestamp": _now_iso(),
        },
        "artifacts": [],
        "metadata": {"nexus.error_code": error.error_code, "nexus.retryable": error.retryable},
    }
    if context_id is not None:
        task["contextId"] = context_id
    return task


def a2a_task_to_outcome(a2a_task: dict[str, Any]) -> Result | ErrorPayload:
    """Inverse of `result_to_a2a_task` / `error_to_a2a_task`."""
    state = a2a_task["status"]["state"]
    if state not in TERMINAL_STATES:
        raise ProtocolError(f"cannot convert non-terminal A2A task state: {state!r}")

    metadata = a2a_task.get("metadata", {})
    if state == "FAILED":
        return ErrorPayload(
            task_id=a2a_task["id"],
            error_code=metadata.get("nexus.error_code", "unknown_error"),
            message=a2a_task["status"].get("message", ""),
            retryable=metadata.get("nexus.retryable", False),
        )

    status = "refused" if state == "REJECTED" else metadata.get("nexus.status", "success")
    # RFC-0001's Result.output is a single dict, but nothing in A2A limits a
    # Task to one non-evidence artifact — an arbitrary A2A agent (the whole
    # point of RFC-0003) could return several. Merge rather than let a
    # later artifact silently clobber an earlier one; last-key-wins only on
    # an actual name collision, not by dropping whole artifacts.
    output: dict[str, Any] = {}
    evidence: list[Evidence] = []
    for artifact in a2a_task.get("artifacts", []):
        if artifact.get("extension") == NEXUS_EVIDENCE_EXTENSION:
            evidence.append(artifact_to_evidence(artifact))
        else:
            for part in artifact.get("parts", []):
                if "structuredData" in part:
                    output.update(part["structuredData"])

    return Result(
        task_id=a2a_task["id"],
        status=status,
        output=output,
        confidence=metadata.get("nexus.confidence"),
        evidence=evidence,
    )
