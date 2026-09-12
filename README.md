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

A reference Python implementation of RFC-0001 (protocol) and RFC-0002
(identity) lives in [`python/`](python/) — no PyPI package yet, install it
locally:

```bash
cd python
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # 155 tests + 1 skipped (pip install -e ".[dev]" pulls in the optional crypto extra;
                              # the skipped test hits the real ruflo CLI — set NEXUS_RUFLO_INTEGRATION=1 to run it)
python examples/quickstart.py
python examples/full_stack.py
python examples/complete_pipeline.py   # graph + audit + trust + arbitration + policy, all at once
```

`NexusCore` is a single-process, in-memory reference orchestrator, not a
networked one — it exists to prove the object model round-trips through
something runnable. Agent selection defaults to "first capable agent," or
weighs evidence-derived trust (RFC-0004, [`nexus/trust.py`](python/src/nexus/trust.py))
when `NexusCore(trust=TrustEvaluator())` is configured. Real interoperability with other
agents follows **RFC-0003 (A2A Alignment)**: Nexus adopts the
[Agent2Agent protocol](https://a2a-protocol.org) as its wire format rather
than inventing its own — see [`python/src/nexus/a2a.py`](python/src/nexus/a2a.py)
for the object-to-A2A-shape mapping (AgentCard, Message, Task, Artifact).
See the module docstrings in [`python/src/nexus/`](python/src/nexus/) for what
each piece does and does not do yet.

Track broader progress in [ROADMAP.md](ROADMAP.md).

## Build an Agent / Connect an AI

```python
from nexus import Agent, NexusCore

core = NexusCore()
agent = Agent(
    name="Tax Specialist",
    capabilities=["tax_analysis", "legislation_search"],
)

@agent.task("analyze_tax")
def analyze(task):
    return {"tax_rate": 0.18, "jurisdiction": task.input.get("jurisdiction")}

core.register(agent)
result_envelope = core.route("analyze_tax", input={"jurisdiction": "MG"})
```

`result_envelope` is `NexusCore`'s internal reference shape. To produce the
actual A2A `Task` another A2A-compliant agent or orchestrator would receive
over the wire (RFC-0003), convert with `nexus.a2a`:

```python
from nexus.a2a import result_to_a2a_task
from nexus.protocol import Result

a2a_task = result_to_a2a_task(Result.from_payload(result_envelope["payload"]))
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
