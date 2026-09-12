# RFC-0002: Agent Identity

- **Status**: Draft
- **Author(s)**: Denilson (Founder / Initial Maintainer)
- **Created**: 2026-09-11
- **Supersedes / Superseded by**: none (extends RFC-0001 §2 additively)

## Summary

This RFC replaces the minimal `{ "agent_id": "..." }` placeholder from
[RFC-0001 §2](0001-nexus-protocol.md) with a full Agent Identity object:
a globally unique `agent_id`, a human-readable `name`, a free-form `role`,
a `capabilities` list, and a `scope`. It also fixes the canonical shape of
`agent_id` itself, which RFC-0001 left open.

## Motivation

RFC-0001 needed *a* value to put in `sender`/`receiver` and deliberately left
its shape undefined. That is no longer sufficient once agents need to be
**discovered** (Level 4, Agent Ecosystem/Discovery) and **routed to by
capability** (Level 2, Nexus Core) rather than addressed by a hardcoded ID.

Rather than design this from scratch, this RFC grounds itself in the
identity/scope model already running in this workspace via Ruflo
(`ai-nexus-open`'s Level-2 dogfood adapter, see
[ARCHITECTURE.md](../../ARCHITECTURE.md)):

- `.swarm/schema.sql`'s `graph_edges` table already keys nodes with a
  **domain-prefixed ID**: `{domain}:{uuid}`, with `agent` as one of the
  domains (`mem`, `agent`, `task`, `entity`, `span`, `pattern`).
- `.claude-flow/CAPABILITIES.md` lists 60+ named agent **roles** (`coder`,
  `researcher`, `security-architect`, ...), but the root `CLAUDE.md` notes
  "any string works as a custom agent type" — i.e. the role name is a label,
  not a unique instance identifier, because a swarm can spawn several
  instances of the same role concurrently.
- `AgentMemoryScope` (ADR referenced in `CAPABILITIES.md`) already
  distinguishes `project` / `local` / `user` memory scopes per agent.

Reusing these conventions means an identity minted under this RFC is already
compatible with the graph and memory system running in this workspace, instead
of requiring a translation layer on day one.

## Design

### 1. `agent_id` (canonical form)

```
agent:<uuid>
```

- `agent` is the fixed domain prefix, matching the `{domain}:{uuid}` scheme
  already used by `graph_edges.source_id` / `target_id` in the Ruflo schema.
- `<uuid>` SHOULD be a ULID (lexicographically sortable, encodes creation
  time) but implementations MAY use UUIDv4; the protocol treats it as an
  opaque unique string either way.
- `agent_id` is minted once per agent **instance** and never reused, even if
  the instance is later destroyed (see Agent Factory lifecycle, Level 4). Two
  instances of the same role (e.g. two `coder` agents in one swarm) MUST have
  different `agent_id`s.

This replaces RFC-0001's illustrative `agent.research.001` form. A static,
human-readable label is still useful for logs and UI, which is what `name`
(§2) is for — it is explicitly not the identifier used for routing or
addressing.

### 2. Full identity object

```json
{
  "agent_id": "agent:01JABC6X6QK8VZ3F9E9YQK1G7T",
  "name": "Tax Specialist",
  "role": "tax-analysis",
  "capabilities": ["tax_analysis", "legislation_search"],
  "scope": "project",
  "model": { "provider": "opaque", "ref": "opaque" }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `agent_id` | string | yes | Canonical form, §1. The only field used for routing/addressing. |
| `name` | string | no | Human-readable label for logs/UI. Not unique, not used for routing. |
| `role` | string | no | Free-form string describing function — deliberately unconstrained, matching Ruflo's "any string works as a custom agent type." Not an enum; the registry (Level 4) is where role vocabularies get curated, not the protocol. |
| `capabilities` | array\<string\> | no | Machine-routable capability tags (e.g. `tax_analysis`). This is what a router matches against — `role` is for humans, `capabilities` is for machines, and the two are allowed to diverge. |
| `scope` | string | no | One of `project`, `local`, `user`, `network`. The first three map directly onto Ruflo's existing `AgentMemoryScope` (project/local/user); `network` is added by this RFC for an agent that registers itself for discovery beyond a single workspace (Level 4). Defaults to `project` if omitted. |
| `model` | object | no | Opaque backing-model reference (provider + ref, both implementation-defined strings). Never used for routing decisions in the protocol itself — that would violate vendor neutrality (§ Alignment, principle 1). Purely informational/audit. |

Per RFC-0001 §7, unknown fields on this object MUST be ignored by consumers
that don't understand them, so a future RFC (e.g. cryptographic identity, see
Open Questions) can add fields here without a `MAJOR` version bump.

### 3. Minimal vs. full identity in envelopes

An RFC-0001 envelope's `sender`/`receiver` MAY carry either:

- the minimal form: `{ "agent_id": "agent:01JABC..." }` — sufficient once the
  receiver already knows the sender (e.g. mid-conversation), or
- the full form (§2) — required the first time an agent is seen, typically
  inside a `control` message of type `capability_announcement`
  (RFC-0001 §6).

A receiver that only has the minimal form and needs the rest (capabilities,
scope) sends a `control_type: capability_query` (RFC-0001 §6) back.

### 4. Registration is local until Level 4

This RFC defines the *shape* of an identity, not a global registry. Until
Level 4 (Nexus Discovery) is designed, an identity is only as discoverable as
its `scope` allows: a `project`-scoped agent is known only within its
workspace's own orchestrator (e.g. this workspace's Ruflo instance via
`agent list`); nothing here implies a public directory yet.

## Alignment with architecture principles

1. **Vendor neutrality** — `model` is opaque and explicitly excluded from
   routing logic; `role`/`capabilities` name no vendor or framework.
2. **Protocol over implementation** — the identity object is plain JSON; any
   orchestrator (Ruflo or otherwise) can produce/consume it without adopting
   this repository's code.
3. **No forced consensus** — not applicable to this RFC.
4. **Evidence before trust** — a `trust` field is deliberately *not* included
   here; trust is derived from historical evidence (Level 6), not
   self-declared identity data. Adding a self-reported trust score here would
   let an agent assert its own reliability, which contradicts that principle.
5. **Simulate before executing** — not applicable to this RFC.
6. **Free/local-first when sufficient** — `scope: project|local|user` lets an
   agent stay fully local and still be addressable, with no requirement to
   register anywhere network-wide.
7. **Everything is observable** — a stable, non-reused `agent_id` is what
   makes a task trace (Level 9) attributable to a specific agent instance
   rather than just a role name shared by many instances.
8. **Anyone can extend it without permission** — `role` and `capabilities`
   are free-form strings; adding a new specialization requires no change to
   this RFC, matching Ruflo's own "any string works as a custom agent type."

## Alternatives considered

- **Dotted namespace as canonical form** (`agent.tax.001`, as used
  illustratively in RFC-0001): rejected as the *canonical* form because it
  does not guarantee uniqueness across independently-spawned instances (two
  people could both mint `agent.tax.001`) and does not match the
  domain-prefixed convention already live in `graph_edges`. Kept as a
  legitimate value for the optional `name` field instead.
- **W3C Decentralized Identifiers (DIDs)**: strictly more powerful
  (cryptographically verifiable, self-sovereign) but heavy for this stage —
  no signing/authentication story exists yet in this RFC series. Because
  `agent_id` is treated as an opaque string by RFC-0001, a future RFC can
  require `agent_id` values to be valid DIDs (`did:method:...`) without
  breaking this one, since the domain-prefix scheme (`agent:<uuid>`) is
  itself a degenerate case of a URN-like identifier.
- **Coupling identity to a specific transport session** (e.g. an MCP session
  ID): rejected — an agent's identity must outlive any single connection so
  that a task trace remains attributable after reconnects; session binding is
  a Level 2 (Nexus Core / message bus) concern layered on top of, not equal
  to, identity.

## Backward compatibility

This RFC is an additive `MINOR` change to the protocol (bumps the illustrative
version in RFC-0001 examples from `1.0` to `1.1`): the minimal
`{ "agent_id": "..." }` shape from RFC-0001 §2 remains valid — it is simply
now documented as the "minimal form" of this RFC's full identity object, and
old messages that only ever carried `agent_id` are unaffected. Only the
*canonical format* of `agent_id` itself changes from an illustrative dotted
example to `agent:<uuid>`; no implementation exists yet to migrate.

## Open questions

- Cryptographic verifiability (signing messages so a receiver can confirm
  `sender.agent_id` wasn't spoofed) is explicitly out of scope here — flagged
  as a candidate RFC-0003, likely built on top of the DID alternative above.
- Should `capabilities` have a controlled vocabulary at the protocol level,
  or stay fully free-form with curation left entirely to a future registry
  (Level 4)? This RFC takes the free-form position; revisit once real
  capability-matching (router) code exists and collisions/typos become a
  measurable problem.
- `scope: network` is defined here but Level 4 (the thing that would make it
  meaningful) does not exist yet — this RFC reserves the value without
  specifying how network-wide discovery actually works.
