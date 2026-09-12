# Roadmap

## Level 0 — Genesis (current)

- [x] Manifesto / README
- [x] Vision & architecture principles
- [x] Governance
- [x] License (Apache 2.0)
- [x] RFC process
- [x] RFC-0001: Nexus Protocol (AI-to-AI message/task/evidence schema) — [draft](docs/rfcs/0001-nexus-protocol.md)
- [x] RFC-0002: Agent Identity — [draft](docs/rfcs/0002-agent-identity.md)
- [ ] Repository structure finalized under the `ai-nexus-open` org

## Level 1 — Nexus Protocol

- [x] AI-to-AI message schema — RFC-0001, reference impl in [`python/src/nexus/protocol.py`](python/src/nexus/protocol.py)
- [x] Task schema — RFC-0001 §4
- [x] Evidence schema — RFC-0001 §5
- [x] Agent identity spec — RFC-0002, reference impl in [`python/src/nexus/identity.py`](python/src/nexus/identity.py)

## Level 2 — Nexus Core

- [x] Router (capability/objective matching) — [`python/src/nexus/core.py`](python/src/nexus/core.py) `NexusCore.route()`
- [x] Orchestrator (single-process, in-memory reference) — same module
- [ ] Message bus (real transport — currently in-process function calls only)
- [x] Agent registry — `NexusCore.register()` / `find_by_capability()`
- [ ] Dogfood adapter: [Ruflo](https://github.com/ruvnet/ruflo) (claude-flow-based
  swarm orchestration) — already configured in this workspace (`.claude-flow/`,
  `.swarm/`, `.mcp.json`); not yet wired to `NexusCore` — next real milestone
  is routing a Nexus task to a Ruflo-spawned agent instead of an in-process
  Python handler, replaceable per the vendor-neutrality principle.

Current reference implementation is intentionally minimal: routing picks the
first capable agent (no cost/trust/load selection — that's Level 6), there is
no policy enforcement of `task.constraints`/`task.risk` (Level 8), and
`NexusCore.trace` is a plain in-memory list, not real observability (Level 9).

## Level 3 — Model Universe

Adapters for OpenAI, Anthropic, Google, Qwen, DeepSeek, ERNIE, Kimi, GLM,
Hunyuan, Doubao, and open-source/local models (Ollama, vLLM, llama.cpp).

## Level 4 — Agent Ecosystem

## Level 5 — Memory + Knowledge

- [x] Obsidian vault connector — [`python/src/nexus/adapters/obsidian.py`](python/src/nexus/adapters/obsidian.py)
  (`ObsidianVault`, writes RFC-0001 §5 Evidence as real Markdown notes with
  YAML frontmatter — a plain folder, no Obsidian install needed to use or test it)

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

## Level 7 — Debate + Arbitration

## Level 8 — Policy + Security

## Level 9 — Execution + Observability

The original vision doc called out Observability as its own concern (tracing,
metrics, audit log) without reserving it a level in this numbered sequence;
it is grouped here with Execution since both are about what happens when a
task actually runs, not about deciding what should run.

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
