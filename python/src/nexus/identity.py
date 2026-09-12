"""Agent Identity — implements RFC-0002.

agent_id canonical form is ``agent:<uuid>`` (RFC-0002 §1), matching the
domain-prefixed node-ID convention already used by Ruflo's graph_edges table
(``.swarm/schema.sql``, domains: mem/agent/task/entity/span/pattern).

RFC-0002 recommends a ULID for sortability; this v0.1 implementation uses
UUID4 to stay dependency-free, since the protocol treats agent_id as an
opaque string either way. Swapping in a ULID generator later is not a
protocol-breaking change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

VALID_SCOPES = {"project", "local", "user", "network"}


class IdentityError(ValueError):
    pass


def new_agent_id() -> str:
    """Mint a new, never-reused agent_id (RFC-0002 §1)."""
    return f"agent:{uuid.uuid4().hex}"


@dataclass
class AgentIdentity:
    agent_id: str = field(default_factory=new_agent_id)
    name: str | None = None
    role: str | None = None
    capabilities: list[str] = field(default_factory=list)
    scope: str = "project"
    model: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.agent_id.startswith("agent:"):
            raise IdentityError(f"agent_id must start with 'agent:': {self.agent_id!r}")
        if self.scope not in VALID_SCOPES:
            raise IdentityError(f"invalid scope: {self.scope!r}")

    def to_dict(self, minimal: bool = False) -> dict[str, Any]:
        """RFC-0002 §3: minimal form for envelopes once a receiver already
        knows the sender; full form otherwise."""
        if minimal:
            return {"agent_id": self.agent_id}
        d: dict[str, Any] = {"agent_id": self.agent_id, "scope": self.scope}
        if self.name is not None:
            d["name"] = self.name
        if self.role is not None:
            d["role"] = self.role
        if self.capabilities:
            d["capabilities"] = self.capabilities
        if self.model is not None:
            d["model"] = self.model
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "AgentIdentity":
        return AgentIdentity(
            agent_id=d["agent_id"],
            name=d.get("name"),
            role=d.get("role"),
            capabilities=list(d.get("capabilities", [])),
            scope=d.get("scope", "project"),
            model=d.get("model"),
        )
