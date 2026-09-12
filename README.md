# AI Nexus Open

**The open infrastructure for interoperable AI agents.**

> Any AI. Any Agent. Any Tool. One Open Protocol.

AI Nexus Open is a model-agnostic, vendor-neutral, open source layer to connect,
coordinate, verify, and govern multiple AI models, agents, and tools. It does not
compete with OpenAI, Anthropic, Google, Meta, or any model provider — it is the
neutral layer that lets all of them interoperate.

> AI Nexus does not replace intelligence. It connects intelligence.

## Why

The AI ecosystem is fragmented: every provider (OpenAI, Anthropic, Google, Meta,
Mistral, DeepSeek, Qwen, and dozens of others) ships its own SDK, its own agent
framework, its own tool-calling format. Every project that wants to use more
than one model ends up re-solving the same problems: routing, memory, evidence,
trust, conflict resolution, policy, and execution safety.

AI Nexus Open exists to solve those problems once, in the open, so no one has to
solve them again per-project or per-vendor.

We are **not**:
- a proprietary AI
- a wrapper around a single chatbot
- a company dependent on one model
- a framework that locks you in

We **are**:
- a protocol
- an infrastructure
- an SDK
- an orchestration layer
- an interoperability layer
- a governance model
- a set of tools for agents

## Architecture

```
                         AI NEXUS OPEN
                              |
            +-----------------+-----------------+
            |                 |                 |
         MODELS            AGENTS             TOOLS
            |                 |                 |
      GPT / Claude       Specialists          APIs
      Gemini / Qwen      Autonomous agents    MCP
      Llama / Mistral    Local AI             Browser / DBs
            |                 |                 |
            +-----------------+-----------------+
                              |
                     NEXUS ORCHESTRATOR
                              |
            +--------+--------+--------+--------+
            |        |        |        |        |
         MEMORY   EVIDENCE   TRUST    DEBATE  REASONING
            +--------+--------+--------+--------+
                              |
                       DECISION ENGINE
                              |
                      POLICY / SECURITY
                              |
                          EXECUTION
                              |
                          VALIDATION
                              |
                            AUDIT
```

No model, framework, or vendor is the core. Everything plugs in through an
**adapter**. If a better framework appears tomorrow, we swap the adapter — the
protocol underneath does not change.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full set of design principles
and the layer breakdown.

## Protocol

The core of the project is the **Nexus Protocol** — an open specification for
AI-to-AI communication (message format, task format, evidence format, agent
identity). Any developer can implement it independently of this repository.

Protocol changes go through the RFC process — see
[docs/rfcs/README.md](docs/rfcs/README.md).

## Quick Start

This is a pre-v0.1 repository. There is no published SDK yet. The current
milestone (**Level 0 — Genesis**) is establishing the manifesto, governance,
license, and RFC process before any protocol code is written.

Track progress in [ROADMAP.md](ROADMAP.md).

## Build an Agent / Connect an AI

Not yet available — pending **Level 1 (Nexus Protocol)** and **Level 2 (Nexus
Core)**. The intended shape (subject to RFC) is a thin Python/TypeScript SDK:

```python
from nexus import Agent

agent = Agent(
    name="Tax Specialist",
    capabilities=["tax_analysis", "legislation_search"],
)

@agent.task("analyze_tax")
def analyze(task):
    ...
```

## Security

See [ARCHITECTURE.md](ARCHITECTURE.md#policy--safety) for the policy/risk model
(human approval gates, simulation before execution, sandboxed tool calls).
Report vulnerabilities per [SECURITY.md](SECURITY.md) once published.

## Governance

AI Nexus Open is a community project, not a personal one. See
[GOVERNANCE.md](GOVERNANCE.md).

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the RFC process in
[docs/rfcs/README.md](docs/rfcs/README.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
