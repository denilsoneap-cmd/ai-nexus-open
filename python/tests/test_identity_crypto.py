from nexus.a2a import to_agent_card
from nexus.identity import AgentIdentity
from nexus.identity_crypto import (
    canonicalize,
    generate_keypair,
    load_or_create_keypair,
    sign,
    sign_agent_card,
    verify,
    verify_agent_card,
)


def test_generate_keypair_returns_32_byte_hex_strings():
    private_hex, public_hex = generate_keypair()
    assert len(bytes.fromhex(private_hex)) == 32
    assert len(bytes.fromhex(public_hex)) == 32


def test_canonicalize_is_order_independent():
    a = canonicalize({"b": 1, "a": 2})
    b = canonicalize({"a": 2, "b": 1})
    assert a == b


def test_canonicalize_excludes_signature_field():
    with_sig = canonicalize({"a": 1, "signature": "deadbeef"})
    without_sig = canonicalize({"a": 1})
    assert with_sig == without_sig


def test_sign_and_verify_round_trip():
    private_hex, public_hex = generate_keypair()
    payload = {"claim": "rate is 18%", "confidence": 0.97}
    signature = sign(payload, private_hex)
    assert verify(payload, signature, public_hex) is True


def test_verify_fails_with_wrong_public_key():
    private_hex, _ = generate_keypair()
    _, other_public_hex = generate_keypair()
    payload = {"claim": "x"}
    signature = sign(payload, private_hex)
    assert verify(payload, signature, other_public_hex) is False


def test_verify_fails_if_payload_tampered_after_signing():
    private_hex, public_hex = generate_keypair()
    payload = {"claim": "x", "confidence": 0.5}
    signature = sign(payload, private_hex)
    payload["confidence"] = 0.99
    assert verify(payload, signature, public_hex) is False


def test_verify_rejects_malformed_signature():
    _, public_hex = generate_keypair()
    assert verify({"a": 1}, "not-hex", public_hex) is False


def test_load_or_create_keypair_persists_across_calls(tmp_path):
    key_path = tmp_path / "key.json"
    first = load_or_create_keypair(key_path)
    second = load_or_create_keypair(key_path)
    assert first == second


def test_sign_and_verify_agent_card_round_trip():
    identity = AgentIdentity(name="Tax Specialist", capabilities=["tax_analysis"])
    card = to_agent_card(identity)
    private_hex, public_hex = generate_keypair()

    signed_card = sign_agent_card(card, private_hex)
    assert "signature" in signed_card
    assert verify_agent_card(signed_card, public_hex) is True


def test_verify_agent_card_fails_without_signature():
    identity = AgentIdentity(name="Tax Specialist")
    card = to_agent_card(identity)
    _, public_hex = generate_keypair()
    assert verify_agent_card(card, public_hex) is False


def test_verify_agent_card_fails_if_card_tampered_after_signing():
    identity = AgentIdentity(name="Tax Specialist", capabilities=["tax_analysis"])
    card = to_agent_card(identity)
    private_hex, public_hex = generate_keypair()

    signed_card = sign_agent_card(card, private_hex)
    signed_card["skills"].append({"name": "injected_capability"})
    assert verify_agent_card(signed_card, public_hex) is False
