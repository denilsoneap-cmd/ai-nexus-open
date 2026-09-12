"""Level 9 (Execution + Observability) — a tamper-evident, hash-chained
audit log.

Adapted from the `audit-event` contract found in this project's own prior
work at `JarvisSN/contracts/audit-event.schema.json`: every event records
`previous_hash` (the prior event's hash) and its own `event_hash` (a SHA-256
digest committing to the event's own fields *and* `previous_hash`). Altering
or deleting any event breaks every hash computed after it, so `AuditLog.verify()`
can prove after the fact whether the log has been tampered with —
`NexusCore.trace` (a plain list) gives ordering but no such guarantee.

This does not make the log tamper-*proof* (it is still an in-memory Python
list an attacker with process access could replace wholesale) — only
tamper-*evident*: a copy taken and checked later will show if the version an
attacker replaced it with doesn't recompute correctly. Real tamper-proofing
needs the events written out to somewhere append-only (a file opened
O_APPEND, a WORM store, etc.), which is future work, not this module's job.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

GENESIS_HASH = "0" * 64


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(fields: dict[str, Any]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(event_id: str, event_type: str, occurred_at: str, actor: str,
                   payload: dict[str, Any], previous_hash: str) -> str:
    digest_input = _canonical({
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "actor": actor,
        "payload": payload,
        "previous_hash": previous_hash,
    })
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_type: str
    occurred_at: str
    actor: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "actor": self.actor,
            "payload": self.payload,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def append(self, event_type: str, actor: str, payload: dict[str, Any]) -> AuditEvent:
        previous_hash = self._events[-1].event_hash if self._events else GENESIS_HASH
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        occurred_at = _now_iso()
        event_hash = _compute_hash(event_id, event_type, occurred_at, actor, payload, previous_hash)
        event = AuditEvent(event_id, event_type, occurred_at, actor, payload, previous_hash, event_hash)
        self._events.append(event)
        return event

    def events(self) -> list[AuditEvent]:
        return list(self._events)

    def verify(self) -> bool:
        """Recompute every event's hash from its fields and confirm the
        chain is unbroken. False means something in the log was altered,
        reordered, or deleted after being appended."""
        expected_previous = GENESIS_HASH
        for event in self._events:
            if event.previous_hash != expected_previous:
                return False
            recomputed = _compute_hash(
                event.event_id, event.event_type, event.occurred_at,
                event.actor, event.payload, event.previous_hash,
            )
            if recomputed != event.event_hash:
                return False
            expected_previous = event.event_hash
        return True
