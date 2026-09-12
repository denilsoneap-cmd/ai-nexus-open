"""Level 4 (Agent Ecosystem / Discovery) — implements RFC-0007: a minimal
registry where agents publish their AgentCard (RFC-0003 §2, produced by
`nexus.a2a.to_agent_card`) and callers discover them by skill, without
needing to already know a specific `agent_id`.

Real A2A discovery is normally an HTTP well-known endpoint
(`/.well-known/agent-card.json`). This project has no HTTP transport yet
(RFC-0003 §1's open question), so this module does not run one — it defines
the registry *interface* plus two backends usable today: `InMemoryRegistry`
(single process) and `FileRegistry` (a shared directory of AgentCard JSON
files, for discovery across processes on the same machine, following the
same "plain files in a directory" idiom as `nexus.transport.filesystem` and
`nexus.adapters.lessons`).

Finding an agent's card here does not mean this project can call it — that
still needs a transport binding to wherever that agent actually lives
(RFC-0007 §5). This module is discovery, not dispatch.

`FileRegistry` is a shared directory anyone with filesystem access can drop
a card into (RFC-0007 Open Questions flags this as a real gap for untrusted
writers) — pass it `trusted_keys` (agent_id -> Ed25519 public key hex, from
`nexus.identity_crypto`) to make `get`/`all`/`find_by_skill` silently drop
any card that isn't validly signed by the key already known for that
agent_id, instead of returning whatever the last writer to that directory
left there. `identity_crypto` (the optional `cryptography` dependency) is
only imported when `trusted_keys` is actually used, so the base SDK stays
dependency-free for every caller that doesn't need it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from .agent import Agent
from .a2a import to_agent_card


class Registry(Protocol):
    def publish(self, card: dict[str, Any]) -> None: ...
    def unpublish(self, agent_id: str) -> None: ...
    def get(self, agent_id: str) -> dict[str, Any] | None: ...
    def find_by_skill(self, skill_name: str) -> list[dict[str, Any]]: ...
    def all(self) -> list[dict[str, Any]]: ...


def _has_skill(card: dict[str, Any], skill_name: str) -> bool:
    return any(skill.get("name") == skill_name for skill in card.get("skills", []))


class InMemoryRegistry:
    def __init__(self) -> None:
        self._cards: dict[str, dict[str, Any]] = {}

    def publish(self, card: dict[str, Any]) -> None:
        self._cards[card["id"]] = card

    def unpublish(self, agent_id: str) -> None:
        self._cards.pop(agent_id, None)

    def get(self, agent_id: str) -> dict[str, Any] | None:
        return self._cards.get(agent_id)

    def find_by_skill(self, skill_name: str) -> list[dict[str, Any]]:
        return [card for card in self._cards.values() if _has_skill(card, skill_name)]

    def all(self) -> list[dict[str, Any]]:
        return list(self._cards.values())


def _safe_stem(agent_id: str) -> str:
    """Filesystem-safe filename stem for an agent_id. agent_id reaches this
    method from wherever a card came from, including a remote publisher
    over a future transport — used unsanitized in a path join, it is a
    path-traversal risk (the exact bug class fixed in
    nexus.adapters.obsidian and nexus.transport.filesystem after the
    2026-09-12 review; not being reintroduced here)."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", agent_id)
    return safe or "agent"


class FileRegistry:
    def __init__(self, path: str | Path, trusted_keys: dict[str, str] | None = None) -> None:
        """`trusted_keys` (optional): agent_id -> Ed25519 public key hex.
        When given, `get`/`all` (and `find_by_skill`, which is built on
        `all`) treat a card as absent unless it carries a valid
        `AgentCardSignature` for its `id` under this map — see the module
        docstring. `None` (the default) preserves the original no-verification
        behavior for callers who haven't set up a trust store yet."""
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.trusted_keys = trusted_keys

    def _file(self, agent_id: str) -> Path:
        return self.path / f"{_safe_stem(agent_id)}.json"

    def _is_trusted(self, card: dict[str, Any]) -> bool:
        if self.trusted_keys is None:
            return True
        public_key = self.trusted_keys.get(card.get("id"))
        if public_key is None:
            return False
        from .identity_crypto import verify_agent_card  # optional dependency — only needed here

        return verify_agent_card(card, public_key)

    def publish(self, card: dict[str, Any]) -> None:
        # A registry entry is replaceable (unlike a transport message) — no
        # locking needed, the latest write is simply the current card.
        self._file(card["id"]).write_text(json.dumps(card, indent=2), encoding="utf-8")

    def unpublish(self, agent_id: str) -> None:
        self._file(agent_id).unlink(missing_ok=True)

    def get(self, agent_id: str) -> dict[str, Any] | None:
        file = self._file(agent_id)
        if not file.exists():
            return None
        card = json.loads(file.read_text(encoding="utf-8"))
        if not self._is_trusted(card):
            return None
        return card

    def all(self) -> list[dict[str, Any]]:
        cards = []
        for file in sorted(self.path.glob("*.json")):
            card = json.loads(file.read_text(encoding="utf-8"))
            if self._is_trusted(card):
                cards.append(card)
        return cards

    def find_by_skill(self, skill_name: str) -> list[dict[str, Any]]:
        return [card for card in self.all() if _has_skill(card, skill_name)]


def publish_agent(registry: Registry, agent: Agent, url: str | None = None) -> None:
    """RFC-0007 §4: publish a locally `register()`-ed Agent's current
    AgentCard to `registry`. Registration (local dispatch) and publication
    (discoverability) are independent — an agent can be one without the
    other. `url`, when given, is where this agent is actually reachable
    over the network (see `nexus.a2a.to_agent_card`) — pass the base URL
    of a real `nexus.transport.a2a_http.build_app` server if this agent is
    served that way, so a remote discoverer can actually dispatch to it,
    not just find that it exists."""
    registry.publish(to_agent_card(agent.identity, url=url))
