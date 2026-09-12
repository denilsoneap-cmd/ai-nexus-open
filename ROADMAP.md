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

## Level 6 — Evidence + Trust

## Level 7 — Debate + Arbitration

## Level 8 — Policy + Security

## Level 9 — Execution

## Level 10 — Multimodal (vision, image, audio, voice, video)

## Level 11 — Workflow (n8n, MCP, automation)

## Level 12 — Graph Intelligence

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
