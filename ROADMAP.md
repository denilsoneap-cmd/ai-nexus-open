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
- [x] Dogfood adapter: [Ruflo](https://github.com/ruvnet/ruflo) —
  [`python/src/nexus/adapters/ruflo.py`](python/src/nexus/adapters/ruflo.py)
  (`make_ruflo_agent`), routes a Nexus task to `ruflo agent spawn -t <type>
  --task <description>`, replaceable per the vendor-neutrality principle
  (an injectable `runner`, same pattern as `adapters/superpowers.py`).
  `list_agents()` (read-only, no LLM cost) verified against the real
  `ruflo v3.41.2` CLI already installed in this workspace — surfaced and
  fixed a real Windows bug along the way: `subprocess.run(["npx", ...])`
  fails with `FileNotFoundError` because `npx`/`ruflo` are `.cmd` shims on
  Windows that `subprocess` can't resolve via bare PATH lookup without
  `shell=True`; fixed by resolving through `shutil.which()` instead, which
  returns the extension-included path. Actually spawning an agent
  (`cli_runner`, the default `runner`) triggers a real LLM call through
  whatever provider Ruflo is configured for — not exercised automatically
  here; the default test suite fakes the runner, and one opt-in test
  (`NEXUS_RUFLO_INTEGRATION=1`) exercises only the free, read-only
  `list_agents()` path against the live CLI.

Current reference implementation is intentionally minimal: routing picks the
first capable agent by default, or the highest-trust one when
`NexusCore(trust=...)` is configured (Level 6, RFC-0004) — cost and load are
still not factored in. `task.risk` is gated when `NexusCore(policy=...)` is
configured (Level 8, RFC-0006); `task.constraints` is still not enforced.
`NexusCore(audit=...)` (see Level 9) gives the trace tamper-evidence.

## Level 3 — Model Universe

Adapters for OpenAI, Anthropic, Google, Qwen, DeepSeek, ERNIE, Kimi, GLM,
Hunyuan, Doubao, and open-source/local models (Ollama, vLLM, llama.cpp).

Every vendor in that original list now has an adapter (14 total,
2026-09-12). `openai.py`/`deepseek.py`/`openrouter.py`/`qwen.py`/
`ernie.py`/`kimi.py`/`glm.py`/`hunyuan.py`/`doubao.py`/`llamacpp.py` share
one HTTP/error-handling/text-extraction helper
([`nexus/adapters/_openai_compatible.py`](python/src/nexus/adapters/_openai_compatible.py))
since they all speak the exact same Chat Completions wire format — added
after a code review flagged the copy-paste cost of the first 4 before the
remaining 5 vendors landed. `anthropic.py`/`google.py`/`ollama.py` stay
bespoke because their wire shapes genuinely differ.

- [x] Registry freshness check — [`python/src/nexus/adapters/registry.py`](python/src/nexus/adapters/registry.py)
  (`check_npm`/`check_pypi`/`compare_versions`), pattern lifted from this
  project's own `mcp-tools/context7-mcp/index.js`, reimplemented in pure
  Python (stdlib `urllib`, no dependency) — a small step toward a real Model
  Registry: knowing when a referenced model/package version has gone stale.
- [x] First real model adapter: Anthropic —
  [`python/src/nexus/adapters/anthropic.py`](python/src/nexus/adapters/anthropic.py)
  (`make_anthropic_agent`, `call_anthropic`), the Messages API over stdlib
  `urllib`, no SDK dependency. The first adapter in this project that calls
  a real, paid LLM — before this, `NexusCore` could route to a workflow, a
  Ruflo-spawned agent, or a filesystem lookup, but never to a raw model
  call. Never exercised for real in this project's own tests (same
  precedent as `nexus.adapters.ruflo.cli_runner`) — tests point `api_url`
  at a local fake server.
- [x] Second real model adapter: OpenAI —
  [`python/src/nexus/adapters/openai.py`](python/src/nexus/adapters/openai.py)
  (`make_openai_agent`, `call_openai`), same shape as the Anthropic adapter
  exactly (`task.input["prompt"]` in, `{text, model, usage}` out) —
  confirms the pattern generalizes rather than being an Anthropic-specific
  one-off, and means `NexusCore.debate()` can now arbitrate between two
  genuinely different model vendors, not just two Python functions.
- [x] Third real model adapter: OpenRouter —
  [`python/src/nexus/adapters/openrouter.py`](python/src/nexus/adapters/openrouter.py)
  (`make_openrouter_agent`, `call_openrouter`), same shape again
  (`task.input["prompt"]` in, `{text, model, usage}` out) — OpenRouter's API
  is itself OpenAI-compatible and routes to dozens of vendors/models by slug
  (e.g. `openai/gpt-4o-mini`), so this one adapter covers a large swath of
  Level 3's remaining vendor list without a bespoke integration per vendor.
- [x] Fourth real model adapter: Google —
  [`python/src/nexus/adapters/google.py`](python/src/nexus/adapters/google.py)
  (`make_google_agent`, `call_google`), Gemini's `generateContent` API.
  Same `{text, model, usage}` contract as the other adapters despite a
  different wire shape underneath (`contents[].parts[].text` instead of
  `messages`, `candidates` instead of `choices`, API key as a URL query
  param instead of an `Authorization` header) — confirms the adapter layer
  actually absorbs vendor differences instead of just aliasing OpenAI's shape.
- [x] Fifth and sixth real model adapters: Qwen and DeepSeek —
  [`python/src/nexus/adapters/qwen.py`](python/src/nexus/adapters/qwen.py) /
  [`python/src/nexus/adapters/deepseek.py`](python/src/nexus/adapters/deepseek.py)
  (`make_qwen_agent`/`call_qwen`, `make_deepseek_agent`/`call_deepseek`) —
  both vendors expose an OpenAI-compatible Chat Completions endpoint, so each
  adapter is a near-identical copy of `openai.py` with a different base URL,
  default model, and API key variable (`QWEN_API_KEY` / `DEEPSEEK_API_KEY`).
- [x] Seventh adapter, first local model: Ollama —
  [`python/src/nexus/adapters/ollama.py`](python/src/nexus/adapters/ollama.py)
  (`make_ollama_agent`, `call_ollama`) — `/api/chat` on a local server, no
  API key, `num_predict` instead of `max_tokens`, usage reported as Ollama's
  own duration/count fields instead of an OpenAI-shaped `usage` object.
  Confirms the adapter contract (`{text, model, usage}`) holds for local,
  free models too, not just paid cloud APIs.
- [x] Eighth adapter, second local one: vLLM —
  [`python/src/nexus/adapters/vllm.py`](python/src/nexus/adapters/vllm.py)
  (`make_vllm_agent`, `call_vllm`) — `/v1/chat/completions` on a self-hosted
  server, same OpenAI-compatible wire shape as `openai.py`/`qwen.py`, but
  `model` is required (no universal default — vLLM serves whatever was
  loaded at startup) and an API key is optional rather than required, since
  vLLM commonly runs unauthenticated on a private network.
- [x] Ninth through thirteenth adapters: ERNIE, Kimi, GLM, Hunyuan, and
  Doubao — [`ernie.py`](python/src/nexus/adapters/ernie.py) /
  [`kimi.py`](python/src/nexus/adapters/kimi.py) /
  [`glm.py`](python/src/nexus/adapters/glm.py) /
  [`hunyuan.py`](python/src/nexus/adapters/hunyuan.py) /
  [`doubao.py`](python/src/nexus/adapters/doubao.py) — all five expose an
  OpenAI-compatible Chat Completions endpoint, so each is a thin wrapper
  around the shared `_openai_compatible` helper. Doubao follows `vllm.py`'s
  pattern (`model` required and keyword-only) rather than a fixed
  `DEFAULT_MODEL`, since Volcengine Ark identifies a deployed model by an
  operator-provisioned endpoint ID, not a shared model name.
- [x] Fourteenth adapter, third local one: llama.cpp —
  [`llamacpp.py`](python/src/nexus/adapters/llamacpp.py) — `llama-server`'s
  own OpenAI-compatible endpoint, same `vllm.py` shape (`model` required
  and keyword-only, no `DEFAULT_MODEL`, optional API key). This closes out
  every vendor named in this Level's original list.

## Level 4 — Agent Ecosystem

- [x] RFC-0007: Agent Discovery Registry —
  [draft](docs/rfcs/0007-agent-discovery-registry.md), reference impl in
  [`python/src/nexus/discovery.py`](python/src/nexus/discovery.py)
  (`InMemoryRegistry`, `FileRegistry`, `publish_agent`) — agents publish
  their AgentCard (RFC-0003 §2) and get found by skill without the caller
  needing to know an `agent_id` in advance. `FileRegistry` reuses the "one
  JSON file per entity in a shared directory" idiom from
  `nexus.transport.filesystem`/`nexus.adapters.lessons`, with the same
  agent_id path-sanitization the 2026-09-12 review added everywhere else.
- [ ] Discovery is not wired into `NexusCore` — finding a card via
  `find_by_skill` does not mean the task can actually be dispatched to that
  agent; that needs a transport binding to wherever it lives (still open,
  RFC-0003 §1). Discovery and dispatch are deliberately independent for now.
- [x] `FileRegistry(path, trusted_keys=...)` — optional agent_id -> Ed25519
  public key map (RFC-0007 Open Questions' flagged gap). When set,
  `get`/`all`/`find_by_skill` silently drop any card that isn't validly
  signed (`nexus.identity_crypto.verify_agent_card`) by the key already
  known for that agent_id, instead of trusting whatever the last writer to
  a shared directory left there. `None` (default) keeps prior behavior for
  callers without a trust store yet; `identity_crypto`'s `cryptography`
  dependency is only imported when `trusted_keys` is actually used, so the
  base SDK stays dependency-free otherwise. Still open: nothing populates
  `trusted_keys` automatically (no key-distribution/pinning mechanism) —
  callers must already know which public key belongs to which agent_id.
- [ ] Agent Factory (dynamic agent creation/destruction) and Agent
  Reputation (the original vision's "GitHub for agents" idea) — not
  started; reputation substantially overlaps with Level 6's trust scoring
  already built and may not need separate machinery.

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

- [x] RFC-0004: Evidence-Derived Trust Scoring —
  [draft](docs/rfcs/0004-evidence-derived-trust.md), reference impl in
  [`python/src/nexus/trust.py`](python/src/nexus/trust.py) (`TrustEvaluator`,
  `TrustScore`) — scores an agent from its own historical Evidence (RFC-0001 §5),
  weighted by `transformation` strength, minus a lessons-recurrence penalty.
  Deliberately narrow: it cannot yet know whether evidence was later
  contradicted or corroborated — that needs Level 7's verdicts.
- [x] Wired into `NexusCore(trust=...)` — when more than one agent is
  capable of an objective, the highest-scoring one is picked instead of
  "first match" (ties, including all-zero-evidence, keep first-match order,
  so `trust=None` — the default — is unaffected). Proven with a real
  behavioral test, not just formula unit tests: two competing agents, the
  worse one registered first, the better one still wins once trust is
  configured.
- [ ] Recurrence penalty attribution — `lessons.py`'s `Lesson` has no
  `agent_id` field yet, so `recurrences` must be supplied by the caller
  today; wiring an actual lesson-to-agent link is open (see RFC-0004 Open
  Questions).

Prior art referenced but not copied (2026-09-12 survey):
`Ruflo/v3/@claude-flow/plugin-agent-federation` has a real trust-tier model
(`TrustLevel` enum + `TrustEvaluator`), a PII-redaction pipeline gating what
crosses a trust boundary, and a `PolicyEngine` that authorizes messages by
trust level + message type + size — plus a "legacy vs. enforce" claim-checker
mode for rolling out policy without breaking existing callers, a pattern
worth reusing when Nexus's own Policy layer (Level 8) is designed. That
system scores *identity/behavior* trust for authorization; RFC-0004 scores
*evidence quality* for routing — different questions, not a duplicate.

## Level 7 — Debate + Arbitration

- [x] RFC-0005: Debate + Arbitration —
  [draft](docs/rfcs/0005-debate-arbitration.md), reference impl in
  [`python/src/nexus/arbitration.py`](python/src/nexus/arbitration.py)
  (`ArbitrationEngine`, `Candidate`, `Verdict`) — reconciles multiple
  agents' results for the same task by comparing per-decision evidence
  strength (reusing RFC-0004's `evidence_strength` formula), never by vote
  count (ARCHITECTURE.md principle 3). Historical trust only breaks an
  exact evidence-strength tie.
- [x] `NexusCore.debate(objective, ...)` — fans a task out to every capable
  agent (or a named subset) and arbitrates; requires `NexusCore(arbiter=...)`.
  A candidate whose handler fails is dropped rather than failing the whole
  debate. Proven with the literal scenario ARCHITECTURE.md principle 3
  names: three agents agreeing on an unsupported answer do not outvote one
  agent with real evidence.
- [ ] Known gaps documented in RFC-0005 §5, not yet addressed: `debate()`
  does not record into `trace`/`audit`/`graph` the way `route()` does;
  fan-out is sequential, not parallel, with no timeout or quorum; no cap
  on how many agents get debated.

## Level 8 — Policy + Security

- [x] RFC-0006: Policy — Risk-Based Approval Gating —
  [draft](docs/rfcs/0006-policy-risk-gating.md), reference impl in
  [`python/src/nexus/policy.py`](python/src/nexus/policy.py)
  (`PolicyEngine`, `PolicyDecision`) — makes `task.risk` (RFC-0001 §4,
  present but unenforced since Genesis) actually gate execution.
  Fails closed: a task whose risk requires approval, with no `approver`
  callback configured, is blocked, not allowed through.
- [x] Wired into `NexusCore(policy=...)` — evaluated right after the task
  envelope is recorded and before any agent lookup; a blocked task still
  shows up in `trace`/`AuditLog` as an ordinary `error` envelope
  (`error_code: "policy_blocked"`), and never reaches an agent's handler.
- [ ] `task.constraints` enforcement (`"no_external_network"`,
  `"max_cost_usd:..."`) — needs adapters to declare what they actually
  touch; not designed yet (RFC-0006 §1/Open Questions).
- [ ] `plan`/`simulate` (the first half of ARCHITECTURE.md principle 5's
  pipeline) — needs agents to expose a dry-run capability; not designed yet.
- [x] Policy also gates `NexusCore.debate()`, not just `route()` — fixed
  same day it was flagged: leaving it unwired meant a caller could bypass
  risk-based approval entirely by using `debate()` for the same objective.
  `debate()` raises `PermissionError` on a non-"allow" decision.

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
