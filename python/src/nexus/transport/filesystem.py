"""A filesystem-backed Message Bus binding for RFC-0003's A2A Message/Task
shapes — one answer to ROADMAP.md Level 2's open "Message bus (real
transport)" item, for same-machine or shared-filesystem multi-agent setups
with no network stack between them.

This is NOT one of A2A's own specified bindings (JSON-RPC/gRPC/HTTP+REST) —
an agent that only speaks this transport cannot interoperate with an
arbitrary external A2A agent over the network. It carries the exact same
payload shapes (`nexus.a2a` dicts), so a receiver that reads a message from
here and one that received it over HTTP see identical JSON.

Ported from the design of this project's own prior work,
`Comunicacao Claude Gpt/CCG-1.2/ccg12.py` ("CCG-1.2"), a Claude<->GPT
messaging protocol already in real use between two other projects on this
machine. Three things are carried over close to verbatim because they solve
real, previously-hit problems, not hypothetical ones:

1. Exclusive-create atomic writes (`os.O_CREAT | os.O_EXCL` + fsync) so two
   writers racing for the same path never silently clobber each other.
2. A claim/complete/release lock per (agent, message) pair, so two processes
   (or two runs of the same agent) never both act on one message.
3. Resolving a message_id to a path with a symlink/parent-containment check,
   so a crafted message_id cannot walk a lookup outside its expected
   directory.

Generalized from CCG's fixed two-actor model (`GPT`/`CLAUDE`) to arbitrary
Nexus `agent_id`s, and from CCG's Markdown+YAML-frontmatter body to raw JSON
(the payloads here are already `nexus.a2a` dicts, so there is no free-text
body to template).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

MESSAGE_ID_RE = re.compile(r"^msg-[0-9a-f]{32}$")


class TransportError(RuntimeError):
    pass


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _new_message_id() -> str:
    return f"msg-{uuid.uuid4().hex}"


def _safe_dir(agent_id: str) -> str:
    """Filesystem-safe directory name for an agent_id like 'agent:<hex>'.

    The character substitution alone is not sufficient: '.' and '-' are
    kept as literal characters (real agent_ids use them), which means an
    agent_id of exactly '..' or '.' passes through unchanged and, joined
    onto a parent path, is a real filesystem parent-directory reference —
    `root / "inbox" / ".."` resolves to `root`, not an inbox at all. Reject
    those results explicitly rather than relying on character filtering
    alone to prevent it."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id)
    if safe in ("", ".", ".."):
        raise TransportError(f"unsafe agent_id for filesystem use: {agent_id!r}")
    return safe


def _validate_message_id(message_id: str) -> None:
    """Every function that turns a message_id into a path must call this
    first — CCG-1.2's `validate_actor_id()` was called at the top of every
    such function; this was missed for `claim`/`complete`/`release`/
    `is_claimed` in the initial port (only `send`'s `responds_to` checked
    it), which would have let a crafted message_id build a path outside its
    expected claims/processed directory (`_exclusive_write` creates
    directories as needed, so this was a real arbitrary-file-write path
    prior to this check, not just a theoretical one)."""
    if not MESSAGE_ID_RE.fullmatch(message_id):
        raise TransportError(f"invalid message_id: {message_id!r}")


def _exclusive_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@dataclass
class Envelope:
    message_id: str
    sender: str
    receiver: str
    kind: Literal["message", "task"]
    payload: dict[str, Any]
    responds_to: str | None = None
    created_at: str = field(default_factory=_now_iso)

    def to_json(self) -> str:
        return json.dumps(
            {
                "message_id": self.message_id,
                "sender": self.sender,
                "receiver": self.receiver,
                "kind": self.kind,
                "responds_to": self.responds_to,
                "created_at": self.created_at,
                "payload": self.payload,
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def from_json(text: str) -> "Envelope":
        return Envelope(**json.loads(text))


class FilesystemTransport:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _inbox(self, agent_id: str) -> Path:
        return self.root / "inbox" / _safe_dir(agent_id)

    def _claims(self, agent_id: str) -> Path:
        return self.root / "claims" / _safe_dir(agent_id)

    def _processed(self, agent_id: str) -> Path:
        return self.root / "processed" / _safe_dir(agent_id)

    def _resolve_in(self, directory: Path, filename: str) -> Path:
        matches = list(directory.glob(filename))
        if len(matches) != 1:
            raise TransportError(
                f"expected exactly one match for {filename!r} in {directory}, found {len(matches)}"
            )
        path = matches[0]
        if path.is_symlink() or path.resolve().parent != directory.resolve():
            raise TransportError(f"{filename!r} resolved outside its expected directory")
        return path

    def send(
        self,
        sender: str,
        receiver: str,
        payload: dict[str, Any],
        kind: Literal["message", "task"] = "message",
        responds_to: str | None = None,
    ) -> str:
        if responds_to is not None and not MESSAGE_ID_RE.fullmatch(responds_to):
            raise TransportError(f"invalid responds_to: {responds_to!r}")
        message_id = _new_message_id()
        envelope = Envelope(
            message_id=message_id, sender=sender, receiver=receiver,
            kind=kind, payload=payload, responds_to=responds_to,
        )
        path = self._inbox(receiver) / f"{message_id}.json"
        _exclusive_write(path, envelope.to_json())
        return message_id

    def pending(self, agent_id: str) -> list[Envelope]:
        inbox = self._inbox(agent_id)
        if not inbox.exists():
            return []
        out = []
        for path in sorted(inbox.glob("msg-*.json")):
            if self._processed(agent_id).joinpath(f"{path.stem}.done.json").exists():
                continue
            out.append(Envelope.from_json(path.read_text(encoding="utf-8")))
        return out

    def is_claimed(self, agent_id: str, message_id: str) -> bool:
        _validate_message_id(message_id)
        return self._claims(agent_id).joinpath(f"{message_id}.claim.json").exists()

    def claim(self, agent_id: str, message_id: str) -> Envelope:
        _validate_message_id(message_id)
        if self._processed(agent_id).joinpath(f"{message_id}.done.json").exists():
            raise TransportError(f"{message_id!r} already processed by {agent_id!r}")
        envelope_path = self._resolve_in(self._inbox(agent_id), f"{message_id}.json")
        envelope = Envelope.from_json(envelope_path.read_text(encoding="utf-8"))
        if envelope.receiver != agent_id:
            raise TransportError(f"{message_id!r} is not addressed to {agent_id!r}")

        claim_path = self._claims(agent_id) / f"{message_id}.claim.json"
        try:
            _exclusive_write(
                claim_path,
                json.dumps({"agent_id": agent_id, "message_id": message_id,
                            "claimed_at": _now_iso(), "pid": os.getpid()}),
            )
        except FileExistsError as exc:
            raise TransportError(f"{message_id!r} is already claimed") from exc

        if self._processed(agent_id).joinpath(f"{message_id}.done.json").exists():
            claim_path.unlink(missing_ok=True)
            raise TransportError(f"{message_id!r} was processed concurrently")
        return envelope

    def complete(self, agent_id: str, message_id: str, response_id: str | None = None) -> None:
        _validate_message_id(message_id)
        claim_path = self._claims(agent_id) / f"{message_id}.claim.json"
        if not claim_path.exists():
            raise TransportError(f"no claim held by {agent_id!r} for {message_id!r}")
        done_path = self._processed(agent_id) / f"{message_id}.done.json"
        _exclusive_write(
            done_path,
            json.dumps({"agent_id": agent_id, "message_id": message_id,
                        "completed_at": _now_iso(), "response_id": response_id}),
        )
        claim_path.unlink()

    def release(self, agent_id: str, message_id: str) -> None:
        _validate_message_id(message_id)
        claim_path = self._claims(agent_id) / f"{message_id}.claim.json"
        if not claim_path.exists():
            raise TransportError(f"no claim held by {agent_id!r} for {message_id!r}")
        claim_path.unlink()

    def doctor(self) -> dict[str, Any]:
        return {"root": str(self.root), "exists": self.root.exists()}

    # -- convenience wrappers around nexus.a2a -----------------------------

    def send_task(self, sender: str, receiver: str, task, context_id: str | None = None) -> str:
        from ..a2a import task_to_a2a_message

        return self.send(sender, receiver, task_to_a2a_message(task, context_id=context_id), kind="message")

    def send_result(
        self, sender: str, receiver: str, result, responds_to: str,
        context_id: str | None = None,
    ) -> str:
        from ..a2a import result_to_a2a_task

        return self.send(
            sender, receiver, result_to_a2a_task(result, context_id=context_id),
            kind="task", responds_to=responds_to,
        )

    def send_error(
        self, sender: str, receiver: str, error, responds_to: str,
        context_id: str | None = None,
    ) -> str:
        from ..a2a import error_to_a2a_task

        return self.send(
            sender, receiver, error_to_a2a_task(error, context_id=context_id),
            kind="task", responds_to=responds_to,
        )
