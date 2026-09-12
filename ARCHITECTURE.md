# Architecture Principles

These principles are binding on every RFC and every subsystem. An RFC that
violates one of these must justify the exception explicitly.

## 1. Vendor neutrality

No model provider, agent framework, or tool vendor is part of the core. GPT,
Claude, Gemini, Qwen, DeepSeek, Llama, MCP, LangGraph, CrewAI, n8n — all of
them are **adapters**, never the core. The core must keep working if any one
adapter disappears.

```
NEXUS CORE
     |
  +--+--+--------+--------+
  |     |        |        |
 MCP  n8n    Ruflo    Framework X
  |     |        |        |
 tools workflows swarm    agents
              orchestration
```

**Ruflo** (github.com/ruvnet/ruflo, a claude-flow-based swarm/agent
orchestration CLI + MCP toolkit) is the initial dogfood adapter for Level 6
(Agent Orchestration) — see [ROADMAP.md](ROADMAP.md). It is chosen because a
working instance is already configured in this workspace, not because it is
privileged in the protocol: it must be replaceable exactly like any other
orchestration backend.

## 2. Protocol over implementation

The Nexus Protocol (message, task, evidence, and identity schemas) is the
contract. Anyone can implement a compliant agent, router, or tool connector
without using this repository's code. The protocol is versioned and changed
only through RFCs.

## 3. No forced consensus

When multiple agents disagree, the system does not average or vote by default.
Disagreement is itself information. The Arbitration Engine looks for the
argument with the strongest evidence, not the most votes.

## 4. Evidence before trust

Every non-trivial claim should be traceable: `claim -> source -> evidence ->
transformation -> confidence`. Trust scores are derived from historical
evidence quality, not asserted.

## 5. Simulate before executing

Any action with real-world side effects (delete, spend, send, deploy) follows:
`plan -> simulate -> assess risk -> approve -> execute -> audit`. Critical-risk
actions require human approval by default; policy is explicit and inspectable,
never implicit in a prompt.

## 6. Free/local-first when sufficient

If a free or local model can satisfy a task, the router should prefer it over
a paid API. Capability should not require an enterprise budget to evaluate.

## 7. Everything is observable

Every task, prompt, tool call, decision, and result is traceable end-to-end.
If a decision cannot be explained after the fact, that is a defect.

## 8. Anyone can extend it without permission

A new model, agent, or tool connects by implementing the protocol and
registering its capabilities — not by a PR being merged into this repository.
The registry is discovery, not gatekeeping.

## Layer breakdown

| Layer | Responsibility |
|---|---|
| 01 Protocol | AI-to-AI message/task/evidence schemas |
| 02 Agent Identity | How an agent identifies and declares capabilities |
| 03 Communication | Message bus between agents |
| 04 Context & Memory | Working / episodic / semantic / shared memory |
| 05 Evidence & Trust | Claim provenance and agent trust scoring |
| 06 Agent Orchestration | Task routing, multi-agent coordination |
| 07 Policy & Safety | Risk assessment, human-approval gates |
| 08 Execution | Sandboxed tool/action execution |
| 09 Observability | Tracing, metrics, audit log |
| 10 Developer Platform | SDKs, CLI, docs, examples |

Each layer is a candidate for its own repository under the `ai-nexus-open`
GitHub organization once it has a merged RFC and a reference implementation.
