"""Nexus Protocol v1.1 wire format — implements RFC-0001 and RFC-0002.

See ../../docs/rfcs/0001-nexus-protocol.md and 0002-agent-identity.md.
Every function here works on plain dicts as the wire representation; the
dataclasses are a convenience for building/reading those dicts, not a
replacement for them — the wire format is JSON, per RFC-0001 §7.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

PROTOCOL_VERSION = "1.1"

MESSAGE_TYPES = {"task", "result", "evidence", "error", "control"}
RESULT_STATUSES = {"success", "partial", "refused"}
TRANSFORMATIONS = {"extracted_verbatim", "summarized", "computed", "inferred"}
RISK_LEVELS = {"low", "medium", "high", "critical"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_message_id() -> str:
    return f"msg-{uuid.uuid4().hex[:12]}"


class ProtocolError(ValueError):
    """Raised when a message does not conform to the Nexus Protocol."""


# ---------------------------------------------------------------------------
# Envelope (RFC-0001 §1)
# ---------------------------------------------------------------------------


def envelope(
    message_type: str,
    sender: dict[str, Any],
    payload: dict[str, Any],
    receiver: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    version: str = PROTOCOL_VERSION,
) -> dict[str, Any]:
    """Build a conformant Nexus envelope around `payload`."""
    if message_type not in MESSAGE_TYPES:
        raise ProtocolError(f"unknown message_type: {message_type!r}")
    msg: dict[str, Any] = {
        "protocol": "nexus",
        "version": version,
        "message_id": new_message_id(),
        "message_type": message_type,
        "timestamp": _now_iso(),
        "sender": sender,
        "correlation_id": correlation_id,
        "payload": payload,
    }
    if receiver is not None:
        msg["receiver"] = receiver
    return msg


def validate_envelope(msg: dict[str, Any]) -> None:
    """Raise ProtocolError if `msg` does not conform to RFC-0001 §1/§7."""
    if msg.get("protocol") != "nexus":
        raise ProtocolError("missing or wrong 'protocol' field")
    version = msg.get("version")
    if not isinstance(version, str) or "." not in version:
        raise ProtocolError(f"malformed version: {version!r}")
    major = version.split(".", 1)[0]
    if major != PROTOCOL_VERSION.split(".", 1)[0]:
        # RFC-0001 §7: reject unsupported MAJOR, accept newer MINOR.
        raise ProtocolError(f"unsupported protocol major version: {version!r}")
    for req in ("message_id", "message_type", "timestamp", "sender", "payload"):
        if req not in msg:
            raise ProtocolError(f"missing required field: {req!r}")
    if msg["message_type"] not in MESSAGE_TYPES:
        raise ProtocolError(f"unknown message_type: {msg['message_type']!r}")
    if "agent_id" not in msg["sender"]:
        raise ProtocolError("sender missing agent_id")


# ---------------------------------------------------------------------------
# Evidence (RFC-0001 §5)
# ---------------------------------------------------------------------------


@dataclass
class Evidence:
    claim: str
    source: str
    agent_id: str
    transformation: str
    confidence: float
    retrieved_at: str = field(default_factory=_now_iso)
    location: str | None = None

    def __post_init__(self) -> None:
        if self.transformation not in TRANSFORMATIONS:
            raise ProtocolError(f"invalid transformation: {self.transformation!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ProtocolError(f"confidence out of range: {self.confidence!r}")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "claim": self.claim,
            "source": self.source,
            "retrieved_at": self.retrieved_at,
            "transformation": self.transformation,
            "confidence": self.confidence,
            "agent_id": self.agent_id,
        }
        if self.location is not None:
            d["location"] = self.location
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Evidence":
        return Evidence(
            claim=d["claim"],
            source=d["source"],
            agent_id=d["agent_id"],
            transformation=d["transformation"],
            confidence=d["confidence"],
            retrieved_at=d.get("retrieved_at", _now_iso()),
            location=d.get("location"),
        )


# ---------------------------------------------------------------------------
# Task / Result / Error (RFC-0001 §4)
# ---------------------------------------------------------------------------


@dataclass
class Task:
    id: str
    objective: str
    input: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    risk: str | None = None
    deadline: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.risk is not None and self.risk not in RISK_LEVELS:
            raise ProtocolError(f"invalid risk level: {self.risk!r}")

    def to_payload(self) -> dict[str, Any]:
        task: dict[str, Any] = {"id": self.id, "objective": self.objective}
        if self.input:
            task["input"] = self.input
        if self.constraints:
            task["constraints"] = self.constraints
        if self.risk is not None:
            task["risk"] = self.risk
        if self.deadline is not None:
            task["deadline"] = self.deadline
        return {"task": task, "context": self.context}

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "Task":
        t = payload["task"]
        return Task(
            id=t["id"],
            objective=t["objective"],
            input=t.get("input", {}),
            constraints=t.get("constraints", []),
            risk=t.get("risk"),
            deadline=t.get("deadline"),
            context=payload.get("context", {}),
        )


@dataclass
class Result:
    task_id: str
    status: str = "success"
    output: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    evidence: list[Evidence] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in RESULT_STATUSES:
            raise ProtocolError(f"invalid result status: {self.status!r}")

    def to_payload(self) -> dict[str, Any]:
        d: dict[str, Any] = {"task_id": self.task_id, "status": self.status, "output": self.output}
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.evidence:
            d["evidence"] = [e.to_dict() for e in self.evidence]
        return d

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "Result":
        return Result(
            task_id=payload["task_id"],
            status=payload.get("status", "success"),
            output=payload.get("output", {}),
            confidence=payload.get("confidence"),
            evidence=[Evidence.from_dict(e) for e in payload.get("evidence", [])],
        )


@dataclass
class ErrorPayload:
    task_id: str
    error_code: str
    message: str
    retryable: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "error_code": self.error_code,
            "message": self.message,
            "retryable": self.retryable,
        }

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "ErrorPayload":
        return ErrorPayload(
            task_id=payload["task_id"],
            error_code=payload["error_code"],
            message=payload["message"],
            retryable=payload.get("retryable", False),
        )
