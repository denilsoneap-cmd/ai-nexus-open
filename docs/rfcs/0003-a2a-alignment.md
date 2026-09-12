# RFC-0003: A2A Alignment — Nexus as an Extension Layer over Agent2Agent

- **Status**: Draft
- **Author(s)**: Denilson (Founder / Initial Maintainer)
- **Created**: 2026-09-12
- **Supersedes**: [RFC-0001](0001-nexus-protocol.md), [RFC-0002](0002-agent-identity.md)

## Summary

This RFC replaces Nexus's own wire envelope (RFC-0001) and identity format
(RFC-0002) with the **Agent2Agent (A2A) Protocol** — Google's agent
interoperability standard, now hosted by the Agentic AI Foundation (a Linux
Foundation project) with 250+ member organizations including Google,
Microsoft, Amazon, Anthropic, and OpenAI. Nexus stops inventing a competing
transport/identity format and becomes an **extension layer on top of A2A**:
Evidence, Trust, Debate/Arbitration, and Policy — the layers A2A and its
companion projects (MCP, AGNTCY) do not themselves define.

## Motivation

RFC-0001/0002 were written and merged before this project's founder had
surveyed the current state of agent-interoperability standards. That survey
(2026-09-12) found:

- **A2A** is a production-grade, multi-vendor open standard for exactly the
  problem RFC-0001 was solving (AI-to-AI task delegation), already backed by
  Google, Microsoft, Amazon, Anthropic, and OpenAI — the same "no single
  vendor owns the protocol" outcome [ARCHITECTURE.md](../../ARCHITECTURE.md)
  principle 1 asks for, but already achieved at a scale this project cannot
  reach independently.
- **AGNTCY** (Cisco, also Linux Foundation) layers discovery, group
  communication, identity, and observability on top of A2A + MCP — covering
  much of what this project's Level 4 (Agent Ecosystem) intended to build.
- **MCP** (Anthropic) already covers agent-to-tool connection, which
  ARCHITECTURE.md's adapter diagram always treated as external to the core.

Continuing to develop RFC-0001's independent envelope would mean asking every
future integrator to implement a second, Nexus-specific protocol alongside
A2A just to talk to a Nexus agent — recreating the exact fragmentation this
project's manifesto says it exists to remove. The honest, principle-1-
consistent move is to adopt the standard that already won multi-vendor
adoption, and put this project's engineering effort into the layers that
standard does not (yet) provide well: **evidence provenance, multi-agent
disagreement resolution, and evidence-derived trust scoring** (Level 6/7 in
[ROADMAP.md](../../ROADMAP.md)) — which, per the 2026-09-12 survey, remain
open problems even in the frameworks (LangGraph, CrewAI, Semantic Kernel,
Microsoft's Agent Governance Toolkit) built on top of A2A/MCP today.

## Design

### 1. Transport and object model: adopt A2A as-is

Nexus no longer defines its own envelope. A Nexus-compliant agent **is** an
A2A-compliant agent: it publishes an **AgentCard**, accepts A2A `Message`s,
and returns A2A `Task`s with `artifacts`. Nexus does not re-specify these —
implementers follow the A2A specification (a2a-protocol.org) directly for
transport (JSON-RPC 2.0, gRPC, or HTTP+JSON/REST — implementer's choice, per
A2A's own multi-binding design) and the base Task lifecycle
(`SUBMITTED -> WORKING -> {COMPLETED | FAILED | CANCELED | REJECTED}`, plus
the interrupted states `INPUT_REQUIRED` / `AUTH_REQUIRED`).

### 2. Identity: AgentCard replaces RFC-0002's `agent_id`

| RFC-0002 concept | A2A equivalent |
|---|---|
| `agent_id` (`agent:<uuid>`) | AgentCard `id` (A2A does not mandate a format; Nexus implementations SHOULD still use `agent:<uuid>` here for continuity with the graph-node convention in `.swarm/schema.sql` and [`nexus/adapters/graph.py`](../../python/src/nexus/adapters/graph.py) — this is a Nexus convention layered on an A2A field, not a protocol requirement) |
| `name` | AgentCard `provider.name` |
| `capabilities` | AgentCard `skills[].name` (an `AgentSkill` also carries input/output schemas, which RFC-0002's flat capability tags did not) |
| `scope` | Not an A2A concept. Nexus keeps this as `metadata.scope` on the AgentCard (`project`/`local`/`user`/`network`) — A2A's `metadata` fields are explicitly designed for exactly this kind of non-standard extension data. |
| `model` | Not part of the AgentCard by design (A2A treats the backing model as an implementation detail, matching this project's own vendor-neutrality principle already). Nexus implementations MAY still record it in `metadata.model` for audit purposes. |

RFC-0002's identity object is not deleted — see RFC-0002 for the reasoning
behind the `scope` field and why a self-reported `trust` field is deliberately
absent; both still apply, now expressed as AgentCard `metadata`.

### 3. Task, input, and constraints: A2A `Message`/`Task` + `metadata`

A Nexus task is an A2A `Message` with `role: "agent"` (when sent
orchestrator-to-agent) whose `parts` include one `structuredData` part
shaped like RFC-0001's old `task.input`, plus:

```json
{
  "messageId": "msg-...",
  "taskId": null,
  "role": "agent",
  "parts": [
    { "structuredData": { "jurisdiction": "MG" } }
  ],
  "metadata": {
    "nexus.objective": "analyze_tax",
    "nexus.constraints": ["max_cost_usd:0.50"],
    "nexus.risk": "high"
  }
}
```

`nexus.objective` replaces RFC-0001's `task.objective` as the machine-routable
verb — A2A's own `AgentSkill.name` (from the AgentCard) is the primary
routing signal where a router is choosing *which agent*; `nexus.objective`
is still useful once an agent has multiple skills.

`nexus.constraints` and `nexus.risk` are unchanged in meaning from RFC-0001
§4 — they now live in A2A's `metadata` map instead of a Nexus-specific
`task` object, per A2A's own extension mechanism.

### 4. Evidence: a registered A2A extension

RFC-0001 §5's Evidence schema is preserved **verbatim** as a payload shape,
but it now travels as a `structuredData` Part inside an A2A `Artifact`,
declared as a **Nexus extension** (A2A's `extensions` array on `AgentCard`
and `Message` exists exactly for this):

```
extension URI: https://ai-nexus-open.org/extensions/evidence/v1
```

(This URI is a namespacing identifier, not yet a resolvable document — it
follows the pattern of an XML/JSON-LD namespace URI. It becomes real once
this project publishes the extension's JSON Schema at that path; until then,
the schema of record is RFC-0001 §5, reproduced unchanged below.)

```json
{
  "id": "artifact-1",
  "mediaType": "application/json",
  "parts": [
    {
      "structuredData": {
        "claim": "The ICMS-ST rate for this product in MG is 18%.",
        "source": "official.gov.br",
        "location": "Article 15",
        "retrieved_at": "2026-09-08T00:00:00Z",
        "transformation": "extracted_verbatim",
        "confidence": 0.97,
        "agent_id": "agent:01JABC..."
      }
    }
  ]
}
```

An agent that does not declare the evidence extension URI in its AgentCard
is not expected to produce or understand this shape — it is additive, per
A2A's own extension-versioning design, not a fork of the base protocol.

### 5. Error mapping

| RFC-0001 `error_code` | A2A equivalent |
|---|---|
| `capability_unavailable` | A2A `UnsupportedOperationError`, or simply no matching `AgentSkill` in the target's AgentCard (a discovery-time failure rather than a task-time one, which is a strict improvement — the caller can know before sending) |
| generic handler failure | Task state `FAILED`, with `status.message` carrying the human-readable reason |
| refused | Task state `REJECTED` |
| retryable errors | Left to the transport binding (HTTP status codes / gRPC status codes / JSON-RPC error objects, per A2A's per-binding error mapping) |

Nexus's `ErrorPayload.retryable` boolean does not have a direct A2A field;
implementations SHOULD encode it as `metadata.retryable` on the terminal
Task's `status` until/unless a future A2A revision adds one.

### 6. What Nexus still owns

Per the Motivation section, Nexus's remaining, non-duplicated scope is:

- **Evidence** (§4 above) — provenance chains A2A does not specify.
- **Trust** (Level 6) — scoring derived from evidence quality over time,
  distinct from Microsoft's Agent Governance Toolkit's behavior-based trust
  scoring (0-1000 identity/behavior trust) found in the 2026-09-12 survey;
  Nexus's trust is specifically **evidence-quality-derived**, a narrower and
  currently-unaddressed niche.
- **Debate + Arbitration** (Level 7) — reconciling multiple agents'
  conflicting A2A `Task` results for the same logical question. A2A has no
  concept of "send the same request to five agents and adjudicate."
- **Policy simulation** (Level 8) — plan/simulate/risk-assess/approve before
  a side-effecting A2A task is sent, per ARCHITECTURE.md principle 5.

These remain Nexus-specific RFCs to be written (not yet drafted).

## Alignment with architecture principles

1. **Vendor neutrality** — strengthened, not weakened: A2A already has more
   vendor buy-in (Google/Microsoft/Amazon/Anthropic/OpenAI) than Nexus could
   independently achieve. Depending on A2A is not depending on a vendor; A2A
   is itself vendor-neutral per its Linux Foundation governance.
2. **Protocol over implementation** — unchanged in spirit; Nexus now points
   implementers at an externally-specified protocol instead of its own,
   which is a stronger version of the same principle.
3. **No forced consensus** — unaffected; Debate/Arbitration (§6) still
   reconciles disagreement rather than voting.
4. **Evidence before trust** — unaffected; §4 preserves the evidence schema
   exactly, now as a registered extension instead of a bespoke envelope.
5. **Simulate before executing** — unaffected; Policy (§6) still gates
   side-effecting actions, now gating the sending of an A2A message/task.
6. **Free/local-first when sufficient** — unaffected; orthogonal to
   transport choice.
7. **Everything is observable** — A2A's `Task.history` (array of Messages)
   gives this project a *better* audit trail primitive than RFC-0001's flat
   `trace` list, for free.
8. **Anyone can extend it without permission** — directly enabled by A2A's
   extension-URI mechanism (§4); arguably better-supported than RFC-0001's
   "ignore unknown fields" rule, since A2A extensions are declared and
   versioned explicitly in the AgentCard rather than silently tolerated.

## Alternatives considered

- **Do nothing, keep RFC-0001/0002**: rejected per Motivation — this is
  exactly the fragmentation the project's manifesto opposes, now made worse
  by A2A's actual multi-vendor adoption making an independent format harder
  to justify, not easier.
- **Adopt MCP instead of A2A**: rejected — MCP is a model-to-tool protocol
  (a single agent calling a tool/data source), not an agent-to-agent
  protocol; conflating the two was already identified as a mistake in
  RFC-0001's own "Alternatives considered" section. MCP remains a Level 11
  adapter target, unchanged, alongside A2A.
- **Adopt AGNTCY instead of / as well as A2A**: AGNTCY builds on A2A + MCP
  rather than replacing them, so this is not actually an alternative to A2A —
  it is a candidate future addition for discovery/observability (Level 4/9)
  once Nexus needs network-wide agent discovery beyond a single workspace.
  Not adopted in this RFC to keep scope to the transport/identity swap only.

## Backward compatibility

This is a breaking change to RFC-0001/0002's wire format. There is no
external adopter yet (this project has no released SDK version beyond
`0.1.0`, unpublished to any package index), so there is no migration path to
design — [`python/src/nexus/protocol.py`](../../python/src/nexus/protocol.py)
and [`identity.py`](../../python/src/nexus/identity.py) will be reworked to
produce/consume A2A shapes directly, and RFC-0001/0002 are marked
`Superseded` rather than deleted, per this project's own RFC process
(`docs/rfcs/README.md`: "Superseded (if replaced by a later RFC)").

## Open questions

- Should the Evidence extension URI (§4) be registered with an actual
  resolvable schema before any external party depends on it? Yes, before
  v0.2 — tracked as a ROADMAP item, not blocking this RFC's acceptance.
- A2A's AgentSkill-based routing (skills declared per-agent) and Nexus's
  current `NexusCore.find_by_capability()` (a flat tag list) are not the same
  shape — reconciling `AgentSkill`'s richer input/output-schema declaration
  with the existing Python reference implementation is deferred to the
  implementation PR, not resolved here.
- AGNTCY (Alternatives Considered) may become relevant sooner than expected
  if Level 4 (Agent Ecosystem/Discovery) work starts before Nexus has its own
  discovery story — revisit then rather than speculate now.
