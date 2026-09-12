# RFC-0007: Agent Discovery Registry

- **Status**: Draft
- **Author(s)**: Denilson (Founder / Initial Maintainer)
- **Created**: 2026-09-12
- **Supersedes / Superseded by**: none (implements ROADMAP.md Level 4)

## Summary

This RFC defines a minimal registry where agents publish their AgentCard
(RFC-0003 §2) and callers discover them by skill, without needing to already
know a specific `agent_id`. It comes in two forms sharing one interface: an
in-memory `Registry` for a single process, and a filesystem-backed
`FileRegistry` — one AgentCard JSON file per agent in a shared directory —
for discovery across processes on the same machine, following the same
"plain files in a directory" idiom `nexus.transport.filesystem` and
`nexus.adapters.lessons` already use.

## Motivation

Both RFC-0002 and RFC-0003 explicitly deferred this. RFC-0002 §4: "This RFC
defines the *shape* of an identity, not a global registry... nothing here
implies a public directory yet." RFC-0003 §6 lists Discovery under "what
Nexus still owns" but never designed it. RFC-0002 also reserved a `scope:
"network"` value on `AgentIdentity` specifically "for an agent that
registers itself for discovery beyond a single workspace" — a value that,
until this RFC, nothing actually used for anything.

Real A2A discovery is normally an HTTP well-known endpoint
(`/.well-known/agent-card.json`) — confirmed as already implemented in
`Ruflo/v3/@claude-flow/plugin-agent-federation`'s own A2A support
(`toAgentCard`/`startAgentCardServer`, found in the 2026-09-12 survey). This
project has no HTTP transport yet (RFC-0003 §1's open question), so this RFC
does not attempt to be that endpoint. It defines the registry *interface*
and a filesystem-backed implementation usable today, leaving an HTTP-backed
implementation as a straightforward addition once a networked transport
exists — same shape, different backend, exactly like
`nexus.transport.filesystem` relates to a future networked A2A binding.

## Design

### 1. Registry interface

```python
class Registry(Protocol):
    def publish(self, card: dict) -> None: ...
    def unpublish(self, agent_id: str) -> None: ...
    def get(self, agent_id: str) -> dict | None: ...
    def find_by_skill(self, skill_name: str) -> list[dict]: ...
    def all(self) -> list[dict]: ...
```

`card` is exactly the dict `nexus.a2a.to_agent_card()` produces — this RFC
adds no new schema. `find_by_skill` matches against the AgentCard's
`skills[].name` array (RFC-0003 §2), not the older RFC-0002 flat
`capabilities` list, since AgentCard is now the identity's canonical wire
form.

### 2. `InMemoryRegistry`

A plain dict keyed by `agent_id`. Exists for tests and single-process use
where a `FileRegistry` would be pure overhead.

### 3. `FileRegistry`

```python
class FileRegistry:
    def __init__(self, path: str | Path) -> None: ...
    def publish(self, card: dict) -> None:
        # writes <path>/<safe_stem(agent_id)>.json
    def find_by_skill(self, skill_name: str) -> list[dict]:
        # reads every *.json in <path>, filters by skill
```

`agent_id` is sanitized before touching a path — the same class of bug
fixed in `nexus.adapters.obsidian` after the 2026-09-12 review (an
externally-supplied identifier used unsanitized in a path join is a path-
traversal risk) is not being reintroduced here.

Unlike `nexus.transport.filesystem.FilesystemTransport` (append-only
messages, needs claim/complete locking so two readers don't double-process
one message), a registry entry is a **replaceable** record — publishing
again just overwrites the file. No locking is needed because there is no
"process exactly once" semantics to protect; the latest write wins, which is
the correct behavior for "here is my current AgentCard."

### 4. Publishing a local `Agent`

```python
def publish_agent(registry: Registry, agent: Agent) -> None:
    registry.publish(to_agent_card(agent.identity))
```

A thin helper, not a `NexusCore` method — registration with `NexusCore`
(local dispatch) and publication to a `Registry` (discoverability) are
different concerns. An agent can be registered locally without being
published (a private, workspace-only agent — RFC-0002's `scope: "project"`),
or published without ever being registered with this particular
`NexusCore` (discovered from elsewhere, dispatched through a transport this
RFC does not define).

### 5. What this RFC deliberately does not do

- **No task dispatch to a discovered agent.** Finding an agent's AgentCard
  via `find_by_skill` does not mean this project can *call* it — that needs
  a transport binding to wherever that agent actually lives (RFC-0003 §1's
  open networked-transport question, unchanged by this RFC).
- **No `NexusCore` integration.** `find_by_objective`/`find_by_capability`
  are unaffected; they still only see locally `register()`-ed agents. Wiring
  discovery into routing (e.g., "if no local agent can do this, check the
  registry") is a natural next step, not this RFC's.
- **No staleness/expiry.** A `FileRegistry` entry for an agent that no
  longer exists sits there until `unpublish()` is called explicitly. No
  heartbeat, no TTL.
- **No trust/verification of a discovered card.** Nothing here checks an
  `AgentCardSignature` (RFC-0003 §2's optional field,
  `nexus.identity_crypto`'s Ed25519 signing) before accepting a published
  card as genuine. A `FileRegistry` shared with untrusted writers is not
  safe to trust blindly — see Open Questions.

## Alignment with architecture principles

1. **Vendor neutrality** — the registry only stores/serves AgentCard dicts;
   nothing here is vendor-specific.
2. **Protocol over implementation** — no new schema; reuses
   `nexus.a2a.to_agent_card()`'s existing output exactly.
3. **No forced consensus** — not applicable.
4. **Evidence before trust** — a discovered card is not trusted by virtue of
   being found; nothing here grants a discovered agent any privilege (see
   §5's explicit non-verification gap).
5. **Simulate before executing** — not applicable; this RFC never executes
   anything.
6. **Free/local-first when sufficient** — `InMemoryRegistry`/`FileRegistry`
   both work fully offline, no network or paid service required to
   discover an agent on the same machine.
7. **Everything is observable** — `Registry.all()` lets a caller inspect the
   full known set at any time; nothing is hidden behind an opaque lookup.
8. **Anyone can extend it without permission** — publishing requires no
   approval from this project; any agent can call `publish_agent()` against
   a shared `FileRegistry` directory it has write access to.

## Alternatives considered

- **Implementing the A2A well-known HTTP endpoint directly**: rejected for
  this RFC — this project has no HTTP server anywhere yet (RFC-0003 §1); a
  discovery-specific HTTP server would be built and thrown away once a real
  networked transport exists. The `Registry` interface is designed so an
  HTTP-backed implementation can be added later without changing callers.
- **A DHT/gossip-based decentralized registry** (matching AGNTCY's
  discovery ambitions, referenced in RFC-0003's Alternatives Considered):
  far more capable, far more machinery than this project needs at its
  current single-workspace scale. `AGNTCY` remains the candidate to adopt
  wholesale if/when network-wide discovery actually matters, per RFC-0003's
  own note — not something to partially reinvent here.
- **Baking discovery into `NexusCore` directly** (a `core.discover()`
  method): rejected to keep `NexusCore` (local dispatch) and `Registry`
  (discoverability) independently useful and independently testable, matching
  how `GraphSink`/`AuditSink`/`TrustSource`/`ArbitrationSource`/`PolicySource`
  are all optional, separately-composable dependencies rather than baked-in
  behavior.

## Backward compatibility

Purely additive — a new module, no changes to any existing class's
signature or behavior.

## Open questions

- Should `FileRegistry.find_by_skill` verify `AgentCardSignature`
  (`nexus.identity_crypto.verify_agent_card`) before including a card in
  results, at least optionally? Left out of this RFC — forcing verification
  would make every publisher need a keypair, which is more friction than
  this RFC's minimal scope justifies; but an unverified shared directory is
  a real trust gap for any deployment beyond "just me, locally." Flagged for
  a follow-up once there is a real multi-writer `FileRegistry` deployment to
  design against.
- Wiring discovery into `NexusCore.route()`/`debate()` as a fallback when no
  local agent matches — natural, not designed here, to keep this RFC's diff
  reviewable per the pattern established since RFC-0005.
- Staleness/expiry policy for `FileRegistry` entries — not designed; revisit
  once a real deployment needs to distinguish "this agent is gone" from
  "this agent hasn't been asked anything in a while."
