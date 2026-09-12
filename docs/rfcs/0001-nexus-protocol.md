# RFC-0001: Nexus Protocol — AI-to-AI Message, Task, and Evidence Schema

- **Status**: Draft
- **Author(s)**: Denilson (Founder / Initial Maintainer)
- **Created**: 2026-09-11
- **Supersedes / Superseded by**: none

## Summary

This RFC defines the **Nexus Protocol v1.0** — the wire format two agents (or
an orchestrator and an agent) use to exchange a task, a result, evidence, an
error, or a control message. It is transport-agnostic: the same envelope can
travel over MCP, an HTTP webhook, a message queue, or a local function call.
Any implementation that produces and consumes conformant JSON is a valid
Nexus Protocol participant, whether or not it uses this repository's code.

Agent Identity is intentionally kept minimal here (just enough to route a
message) — the full identity/capability-declaration spec is deferred to
RFC-0002, which this RFC's `agent_id` format is designed to be forward
compatible with.

## Motivation

Without a shared wire format, every pair of agents needs a custom adapter, and
"20 models connected" degenerates into 20 point-to-point integrations. A
protocol lets:

- an orchestrator (e.g. a Ruflo-based swarm, see [ARCHITECTURE.md](../../ARCHITECTURE.md))
  route a task to any conformant agent without knowing its internals;
- an agent built by a third party join the network by implementing one
  schema instead of N vendor SDKs;
- evidence and confidence travel with a result instead of being lost at the
  first hop, which is a prerequisite for the Evidence & Trust and Debate &
  Arbitration layers (Levels 5–7 in [ROADMAP.md](../../ROADMAP.md)).

If we skip this and let Level 2 (Nexus Core) start with an ad hoc format, every
later layer (memory, evidence, trust, policy) inherits an unversioned,
undocumented contract — expensive to fix once agents exist that depend on it.

## Design

### 1. Envelope

Every Nexus message is a single JSON object with this top-level shape:

```json
{
  "protocol": "nexus",
  "version": "1.0",
  "message_id": "msg-6f2a9e",
  "message_type": "task",
  "timestamp": "2026-09-11T14:32:00Z",
  "sender": { "agent_id": "agent.research.001" },
  "receiver": { "agent_id": "agent.tax.001" },
  "correlation_id": null,
  "payload": {}
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `protocol` | string | yes | Always `"nexus"`. |
| `version` | string | yes | Semver of the protocol, e.g. `"1.0"`. See §7. |
| `message_id` | string | yes | Unique per message. Implementations SHOULD use a ULID/UUID. |
| `message_type` | string | yes | One of: `task`, `result`, `evidence`, `error`, `control`. See §3. |
| `timestamp` | string | yes | ISO 8601, UTC. |
| `sender` / `receiver` | object | yes | Minimal Agent Identity — see §2. `receiver` MAY be omitted for broadcast/discovery messages. |
| `correlation_id` | string \| null | no | For a `result`/`error`/`evidence` message, the `message_id` of the `task` it responds to. |
| `payload` | object | yes | Shape depends on `message_type` — see §3–§5. |

### 2. Agent Identity (minimal, this RFC)

```json
{ "agent_id": "agent.<domain>.<instance>" }
```

- `agent_id` is a dotted string: a stable namespace (`agent.tax`,
  `agent.research`, `agent.coding`) plus an instance suffix (`001`, or a
  ULID for dynamically spawned agents — see "Agent Factory" concept in
  [ROADMAP.md](../../ROADMAP.md) Level 4).
- This RFC does not define authentication, public keys, or capability
  declaration — that is RFC-0002's scope. An implementation MAY treat
  `agent_id` as opaque today and extend the object with more fields later
  without breaking this schema, because unknown fields on `sender`/`receiver`
  MUST be ignored by conformant consumers (see §7).

### 3. Message types

| `message_type` | Purpose | Payload schema |
|---|---|---|
| `task` | Ask an agent to do something | §4 |
| `result` | Answer to a `task` | §4.1 |
| `evidence` | A claim + its provenance, attached to a result or sent standalone | §5 |
| `error` | A `task` could not be completed | §4.2 |
| `control` | Handshake / capability query / heartbeat, not domain work | §6 |

A message has exactly one `message_type`; a `result` that carries evidence
embeds it under `payload.evidence` (an array of §5 objects) rather than being
split into separate messages, so a result and its provenance cannot be
separated in transit.

### 4. Task schema (`payload` when `message_type = "task"`)

```json
{
  "task": {
    "id": "task-123",
    "objective": "analyze_tax_rule",
    "input": { "document": "nota-fiscal-882.pdf", "jurisdiction": "MG" },
    "constraints": ["no_external_network", "max_cost_usd:0.50"],
    "risk": "high",
    "deadline": "2026-09-11T15:00:00Z"
  },
  "context": {}
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `task.id` | string | yes | Stable ID for this unit of work; distinct from `message_id` (a task may be retried across several messages sharing one `task.id`). |
| `task.objective` | string | yes | A short machine-routable verb/intent, e.g. `analyze_tax_rule`. Free-form natural language goes in `task.input`, not here. |
| `task.input` | object | no | Objective-specific arguments. |
| `task.constraints` | array\<string\> | no | Machine-checkable limits the receiver must respect (network, cost, time, tools allowed). Enforcement is the Policy layer's job (Level 8); the protocol only carries the declaration. |
| `task.risk` | string | no | One of `low`, `medium`, `high`, `critical` — self-declared by the sender as a hint; the Policy layer is the authority, not this field. |
| `task.deadline` | string | no | ISO 8601. |
| `context` | object | no | Opaque memory/context payload from Level 4 (Context & Memory). This RFC does not define its internal shape. |

#### 4.1 Result schema (`payload` when `message_type = "result"`)

```json
{
  "task_id": "task-123",
  "status": "success",
  "output": { "tax_rate": 0.18, "rule_reference": "ICMS-ST/MG art.15" },
  "confidence": 0.94,
  "evidence": []
}
```

`status` is one of `success`, `partial`, `refused`. `refused` is distinct from
`error` (§4.2): `refused` means the agent understood the task and declined
(e.g. a policy or capability boundary), `error` means it failed to process the
request at all.

#### 4.2 Error schema (`payload` when `message_type = "error"`)

```json
{
  "task_id": "task-123",
  "error_code": "capability_unavailable",
  "message": "No model with jurisdiction=MG tax capability is registered.",
  "retryable": false
}
```

### 5. Evidence schema

```json
{
  "claim": "The ICMS-ST rate for this product in MG is 18%.",
  "source": "official.gov.br",
  "location": "Article 15",
  "retrieved_at": "2026-09-08T00:00:00Z",
  "transformation": "extracted_verbatim",
  "confidence": 0.97,
  "agent_id": "agent.tax.001"
}
```

| Field | Required | Notes |
|---|---|---|
| `claim` | yes | The assertion being backed. |
| `source` | yes | Where it came from — URL, document ID, database record, or another `agent_id` (an agent can be the source of another agent's claim). |
| `location` | no | Pointer within the source (article, page, line, cell). |
| `retrieved_at` | yes | When the evidence was fetched/observed — not when the message was sent. |
| `transformation` | yes | One of `extracted_verbatim`, `summarized`, `computed`, `inferred`. Downstream trust scoring (Level 6) weighs these differently — an `inferred` claim is not evidence-equivalent to `extracted_verbatim`. |
| `confidence` | yes | `0.0`–`1.0`, self-reported by the producing agent. |
| `agent_id` | yes | Who produced this evidence entry. |

### 6. Control messages

Used for capability discovery and liveness, not domain tasks:

```json
{ "control_type": "capability_query" }
{ "control_type": "capability_announcement", "capabilities": ["tax_analysis", "legislation_search"] }
{ "control_type": "heartbeat" }
```

Full agent discovery/registry semantics are deferred to a future RFC (Level 4
in [ROADMAP.md](../../ROADMAP.md)); `control` messages here only cover the
two-agent handshake, not network-wide discovery.

### 7. Versioning rules

- `version` is `MAJOR.MINOR`. A receiver MUST reject a message whose `MAJOR`
  it does not support, and MUST accept (ignoring unknown fields) a message
  whose `MINOR` is newer than what it implements.
- Adding an optional field, or a new `message_type`, is a `MINOR` bump.
  Changing the meaning or removing a field is a `MAJOR` bump and requires a
  new RFC.
- Conformant implementations MUST ignore unrecognized top-level or nested
  fields rather than erroring, so the protocol can grow without breaking
  older agents (this is what makes RFC-0002 able to extend `sender`/
  `receiver` later without a `MAJOR` bump).

## Alignment with architecture principles

1. **Vendor neutrality** — the envelope names no vendor, model, or framework;
   `agent_id` is opaque to any specific provider.
2. **Protocol over implementation** — this RFC defines JSON on the wire, not
   a library. Any language can implement it.
3. **No forced consensus** — a `result` carries one agent's answer plus its
   own `confidence`; reconciling multiple `result`s for the same `task_id` is
   the Arbitration Engine's job (Level 7), not the protocol's.
4. **Evidence before trust** — §5 makes claim/source/confidence a first-class,
   mandatory-shape citizen of the protocol, not an afterthought bolted onto
   `result.output`.
5. **Simulate before executing** — `task.risk` and `task.constraints` give the
   Policy layer (Level 8) the hooks it needs; enforcement itself is out of
   scope for this RFC.
6. **Free/local-first when sufficient** — out of scope for the wire format;
   this is a routing/policy concern (Level 6), not a message-shape concern.
7. **Everything is observable** — every message carries `message_id`,
   `correlation_id`, and `timestamp`, which is the minimum needed to
   reconstruct a task's full trace later (Level 9).
8. **Anyone can extend it without permission** — §7's "ignore unknown fields"
   rule lets any implementer add fields experimentally before they are
   standardized by a future RFC.

## Alternatives considered

- **gRPC/Protobuf instead of JSON**: rejected for v1 — JSON is transport- and
  language-agnostic with zero tooling required to inspect a message by hand,
  which matters for a young, contributor-facing spec. A binary encoding can
  be proposed later as an additive RFC without changing the logical schema.
  - **Reusing MCP's message format directly**: rejected because MCP is a
    tool-context protocol between a model and its tools, not an AI-to-AI task
  protocol between peer agents; conflating the two would violate vendor/
  framework neutrality (MCP would become load-bearing in the core). MCP
  remains a Level-11 adapter (see [ARCHITECTURE.md](../../ARCHITECTURE.md)).
- **Single flat schema for all message types**: rejected — a `task` and an
  `evidence` object have little in common; forcing one shape makes every
  field optional and the schema unreadable. A shared envelope + per-type
  payload (this design) keeps required fields actually required.

## Backward compatibility

This is the first version of the protocol; there is nothing to be compatible
with yet. §7 defines the compatibility rules future RFCs must follow.

## Open questions

- Should `task.constraints` be a flat string array (as shown) or a structured
  object once the Policy layer (Level 8) is designed? Leaving it as strings
  now to avoid over-specifying a layer that doesn't exist yet; revisit in the
  Level 8 RFC.
- Does `correlation_id` need to support fan-out (one `task` producing many
  `result`s from different agents, as in the Research Swarm / Debate
  concepts)? Current design allows multiple messages to share one
  `correlation_id`, but this needs validation once Level 6/7 are designed.
- Transport binding examples (Nexus-over-MCP, Nexus-over-HTTP) would help
  adoption — candidate for a companion non-normative doc rather than part of
  this RFC.
