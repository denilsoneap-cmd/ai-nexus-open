"""Ed25519 signing for AgentCards — A2A's optional `AgentCardSignature`
field (RFC-0003 §2).

Ported from the design of this project's own prior work,
`Ruflo/v3/@claude-flow/plugin-agent-federation` (MIT-licensed): a persisted
Ed25519 keypair per node, and canonical JSON (keys sorted recursively, a
`signature` field excluded, no whitespace) as the exact bytes both signed
and verified — so sign and verify can never disagree over formatting.

That project's own history documents a real bug this design exists to avoid:
an earlier `verifySignature()` there returned `true` unconditionally (a
critical authentication bypass, flagged in their own audit log as
`audit_1776483149979`) before being replaced with real Ed25519 verification.
There is no equivalent stub path here — `verify()` either checks a real
signature against a real public key, or the caller gets `False`, never a
hardcoded pass.

Uses the `cryptography` package (optional dependency — `pip install
"nexus-sdk[crypto]"`) rather than a hand-rolled Ed25519 implementation:
implementing signature primitives from scratch is exactly the kind of thing
a project like this should not do itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonicalize(obj: dict[str, Any]) -> str:
    """Deterministic JSON for signing: keys sorted recursively, no
    whitespace, and any top-level 'signature' field excluded."""
    stripped = {k: v for k, v in obj.items() if k != "signature"}

    def _sort(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _sort(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [_sort(v) for v in value]
        return value

    return json.dumps(_sort(stripped), separators=(",", ":"), sort_keys=True)


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_hex, public_key_hex)."""
    private_key = Ed25519PrivateKey.generate()
    private_hex = private_key.private_bytes_raw().hex()
    public_hex = private_key.public_key().public_bytes_raw().hex()
    return private_hex, public_hex


def load_or_create_keypair(path: str | Path) -> tuple[str, str]:
    """Persist a keypair at `path` so an agent's identity survives restarts
    (mirrors the federation plugin's `key-<nodeId>.json` pattern). Returns
    (private_key_hex, public_key_hex)."""
    path = Path(path)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["private_key"], data["public_key"]

    private_hex, public_hex = generate_keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"private_key": private_hex, "public_key": public_hex}, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best-effort — e.g. Windows doesn't honor POSIX permission bits
    return private_hex, public_hex


def sign(payload: dict[str, Any], private_key_hex: str) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    signature = private_key.sign(canonicalize(payload).encode("utf-8"))
    return signature.hex()


def verify(payload: dict[str, Any], signature_hex: str, public_key_hex: str) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public_key.verify(bytes.fromhex(signature_hex), canonicalize(payload).encode("utf-8"))
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_agent_card(card: dict[str, Any], private_key_hex: str) -> dict[str, Any]:
    """Returns a copy of `card` (see `nexus.a2a.to_agent_card`) with a
    'signature' field added."""
    signed = dict(card)
    signed["signature"] = sign(card, private_key_hex)
    return signed


def verify_agent_card(card: dict[str, Any], public_key_hex: str) -> bool:
    signature = card.get("signature")
    if not signature:
        return False
    return verify(card, signature, public_key_hex)
