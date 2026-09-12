# Roadmap

## Level 0 — Genesis (current)

- [x] Manifesto / README
- [x] Vision & architecture principles
- [x] Governance
- [x] License (Apache 2.0)
- [x] RFC process
- [x] RFC-0001: Nexus Protocol — [superseded](docs/rfcs/0001-nexus-protocol.md) by RFC-0003
- [x] RFC-0002: Agent Identity — [superseded](docs/rfcs/0002-agent-identity.md) by RFC-0003
- [x] RFC-0003: A2A Alignment — [draft](docs/rfcs/0003-a2a-alignment.md) (2026-09-12
  survey found Google's Agent2Agent protocol already has the multi-vendor
  adoption — Google/Microsoft/Amazon/Anthropic/OpenAI, 250+ orgs via the
  Agentic AI Foundation — this project's own manifesto asks for; Nexus adopts
  A2A as its wire format instead of competing with it, see RFC-0003 Motivation)
- [ ] Repository structure finalized under the `ai-nexus-open` org

## Level 1 — Nexus Protocol

- [x] AI-to-AI message schema — now A2A's Message/Task/Artifact model
  (RFC-0003), translated to/from Nexus's Python objects in
  [`python/src/nexus/a2a.py`](python/src/nexus/a2a.py)
- [x] Task schema — RFC-0003 §3 (`nexus.*` A2A metadata keys)
- [x] Evidence schema — RFC-0001 §5, unchanged, now carried as a registered
  A2A extension (RFC-0003 §4)
- [x] Agent identity spec — now an A2A AgentCard (RFC-0003 §2); `agent_id`
  format from RFC-0002 kept by convention, reference impl still in
  [`python/src/nexus/identity.py`](python/src/nexus/identity.py)
- [x] AgentCard signing (A2A's optional `AgentCardSignature`) —
  [`python/src/nexus/identity_crypto.py`](python/src/nexus/identity_crypto.py),
  Ed25519 + canonical JSON, ported from the design of
  `Ruflo/v3/@claude-flow/plugin-agent-federation` (persisted keypair,
  sign/verify never disagree over JSON formatting because both operate on
  the same canonicalized bytes). Optional dependency (`pip install
  "nexus-sdk[crypto]"`) — the base SDK stays dependency-free.
- [x] Filesystem Message Bus binding — [`python/src/nexus/transport/filesystem.py`](python/src/nexus/transport/filesystem.py)
  (`FilesystemTransport`), ported from this project's own prior work in
  `Comunicacao Claude Gpt/CCG-1.2/ccg12.py` (atomic exclusive writes,
  claim/complete/release locking, symlink/path-containment checks); good for
  same-machine/offline multi-agent setups, not one of A2A's own specified
  bindings (see RFC-0003 §1)
- [ ] A real *networked* A2A transport (JSON-RPC/gRPC/HTTP server+client per
  A2A's own spec) — still open; `a2a.py` maps object *shapes*, the
  filesystem transport moves them locally, neither speaks to an external
  A2A agent over a network yet

## Level 2 — Nexus Core

- [x] Router (capability/objective matching) — [`python/src/nexus/core.py`](python/src/nexus/core.py) `NexusCore.route()`
- [x] Orchestrator (single-process, in-memory reference) — same module
- [x] Message bus — filesystem binding done (see Level 1 above); a networked
  binding is still open
- [x] Agent registry — `NexusCore.register()` / `find_by_capability()`
- [ ] Dogfood adapter: [Ruflo](https://github.com/ruvnet/ruflo) (claude-flow-based
  swarm orchestration) — already configured in this workspace (`.claude-flow/`,
  `.swarm/`, `.mcp.json`); not yet wired to `NexusCore` — next real milestone
  is routing a Nexus task to a Ruflo-spawned agent instead of an in-process
  Python handler, replaceable per the vendor-neutrality principle.

Current reference implementation is intentionally minimal: routing picks the
first capable agent (no cost/trust/load selection — that's Level 6), and
there is no policy enforcement of `task.constraints`/`task.risk` (Level 8).
`NexusCore(audit=...)` (see Level 9) gives the trace tamper-evidence, but
routing selection itself is still "first match," not real orchestration.

## Level 3 — Model Universe

Adapters for OpenAI, Anthropic, Google, Qwen, DeepSeek, ERNIE, Kimi, GLM,
Hunyuan, Doubao, and open-source/local models (Ollama, vLLM, llama.cpp).

- [x] Registry freshness check — [`python/src/nexus/adapters/registry.py`](python/src/nexus/adapters/registry.py)
  (`check_npm`/`check_pypi`/`compare_versions`), pattern lifted from this
  project's own `mcp-tools/context7-mcp/index.js`, reimplemented in pure
  Python (stdlib `urllib`, no dependency) — a small step toward a real Model
  Registry: knowing when a referenced model/package version has gone stale.

## Level 4 — Agent Ecosystem

## Level 5 — Memory + Knowledge

- [x] Obsidian vault connector — [`python/src/nexus/adapters/obsidian.py`](python/src/nexus/adapters/obsidian.py)
  (`ObsidianVault`, writes RFC-0001 §5 Evidence as real Markdown notes with
  YAML frontmatter — a plain folder, no Obsidian install needed to use or test it)
- [x] Lessons-learned store — [`python/src/nexus/adapters/lessons.py`](python/src/nexus/adapters/lessons.py)
  (`LessonStore`), ported faithfully from this project's own prior work at
  `Mif-Oracle/scripts/agente_auditor.py` — refuses to record a lesson unless
  its correction names a real mechanism (test/lint/hook/guide/restriction),
  carrying over that project's own principle: "advice doesn't prevent
  anything, a mechanism does." Repeated symptoms increment a `recurrences`
  counter instead of duplicating the lesson. `compile_digest()` produces the
  Markdown meant for session-start context injection, matching that
  project's `carregar-licoes.sh` hook.

Includes the "Great Minds" cognitive-model concept from the original vision
(agent personas grounded in the documented thinking/methods of historical and
contemporary experts, not a claim of recreating anyone's actual mind). This
needs a curated ingestion pipeline from named, reliable, rights-cleared
sources — not an unscoped "everything on the internet" crawl — feeding into
the Obsidian vault ([`python/src/nexus/adapters/obsidian.py`](python/src/nexus/adapters/obsidian.py))
and Graph store ([`python/src/nexus/adapters/graph.py`](python/src/nexus/adapters/graph.py))
already implemented. Source list and licensing terms are an open question,
not yet decided.

## Level 6 — Evidence + Trust

Not yet implemented (only identity signing exists so far — see
`identity_crypto.py` under Level 1). Prior art worth studying before writing
this RFC, found in this project's own workspace (2026-09-12 survey):
`Ruflo/v3/@claude-flow/plugin-agent-federation` has a real trust-tier model
(`TrustLevel` enum + `TrustEvaluator`), a PII-redaction pipeline gating what
crosses a trust boundary, and a `PolicyEngine` that authorizes messages by
trust level + message type + size — plus a "legacy vs. enforce" claim-checker
mode for rolling out policy without breaking existing callers, a pattern
worth reusing when Nexus's own Policy layer (Level 8) is designed. Not
copied here (it is a large, separate MIT-licensed system) — referenced for
when this level's RFC gets written.

## Level 7 — Debate + Arbitration

## Level 8 — Policy + Security

## Level 9 — Execution + Observability

The original vision doc called out Observability as its own concern (tracing,
metrics, audit log) without reserving it a level in this numbered sequence;
it is grouped here with Execution since both are about what happens when a
task actually runs, not about deciding what should run.

- [x] Tamper-evident audit log — [`python/src/nexus/audit.py`](python/src/nexus/audit.py)
  (`AuditLog`), hash-chained events adapted from
  `JarvisSN/contracts/audit-event.schema.json`; `NexusCore(audit=...)` wires
  it in optionally, alongside the plain `trace` list
- [ ] Execution sandboxing, metrics, and a real (not just tamper-evident)
  append-only log destination — still open

## Level 10 — Multimodal (vision, image, audio, voice, video)

Candidate adapters, not yet built (raised 2026-09-11): Google ADK (another
agent-framework adapter, alongside Superpowers), NotebookLM (source-grounded
research/summarization), ElevenLabs (voice), HeyGen (video), Nano Banana
(image generation). Each would follow the same pattern as
[`nexus/adapters/n8n.py`](python/src/nexus/adapters/n8n.py) or
[`nexus/adapters/superpowers.py`](python/src/nexus/adapters/superpowers.py):
a factory producing a plain `Agent`, no core changes required.

## Level 11 — Workflow (n8n, MCP, automation)

- [x] n8n adapter — [`python/src/nexus/adapters/n8n.py`](python/src/nexus/adapters/n8n.py)
  (`N8nAdapter`/`make_n8n_agent`, POSTs a task to a webhook, tested against a
  real local HTTP server, not mocked)
- [x] Agent-skill-framework adapter (covers Superpowers/obra) —
  [`python/src/nexus/adapters/superpowers.py`](python/src/nexus/adapters/superpowers.py)
  (`make_skill_agent`, takes an injected skill-runner so no specific
  framework is load-bearing)
- [ ] MCP transport binding (RFC-0001 open question)

## Level 12 — Graph Intelligence

- [x] `GraphStore` — [`python/src/nexus/adapters/graph.py`](python/src/nexus/adapters/graph.py),
  schema-compatible with (but separate from) Ruflo's live `.swarm/schema.sql`
  `graph_edges` table, so pointing at that file later is a config change, not
  a migration
- [x] `NexusCore(graph=...)` records `routed_to` / `produced_result` /
  `supported_by` edges for every task, agent, and evidence entry automatically

## Level 13 — Self-Correction

## Level 14 — Benchmark (Nexus Bench)

## Level 15 — Global Ecosystem

## Level 16 — Nexus Network

---

## Version milestones

| Version | Scope |
|---|---|
| v0.1 | Protocol + Agent SDK |
| v0.2 | Agent discovery + adapters |
| v0.3 | Shared context + memory |
| v0.4 | Evidence + trust |
| v0.5 | Multi-agent orchestration |
| v0.6 | Debate + arbitration |
| v0.7 | Policy + risk |
| v0.8 | Execution + simulation |
| v0.9 | Observability |
| v1.0 | Open AI Interoperability Platform |

This roadmap is a living document; changes to it happen via ordinary PRs
unless they imply a protocol or governance change, in which case they follow
the RFC process.
