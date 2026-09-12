"""Runnable version of the README's Quick Start example.

    python examples/quickstart.py

Registers a Tax Specialist agent with NexusCore, routes a task to it through
the RFC-0001 envelope format, and prints the resulting `result` envelope.
Also shows the `capability_unavailable` error path for an unregistered
objective, and an agent attaching Evidence (RFC-0001 §5) to its result.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus import Agent, NexusCore, Result, Task  # noqa: E402


def build_core() -> NexusCore:
    core = NexusCore()

    tax_agent = Agent(name="Tax Specialist", capabilities=["tax_analysis", "legislation_search"])

    @tax_agent.task("analyze_tax")
    def analyze(task: Task) -> Result:
        evidence = tax_agent.make_evidence(
            claim="The ICMS-ST rate for this product in MG is 18%.",
            source="official.gov.br",
            transformation="extracted_verbatim",
            confidence=0.97,
            location="Article 15",
        )
        return Result(
            task_id=task.id,
            status="success",
            output={"tax_rate": 0.18, "rule_reference": "ICMS-ST/MG art.15"},
            confidence=0.94,
            evidence=[evidence],
        )

    core.register(tax_agent)
    return core


def main() -> None:
    core = build_core()

    print("--- successful route ---")
    result_envelope = core.route(
        "analyze_tax",
        input={"document": "nota-fiscal-882.pdf", "jurisdiction": "MG"},
    )
    print(json.dumps(result_envelope, indent=2))

    print("\n--- no capable agent registered ---")
    error_envelope = core.route("translate_document")
    print(json.dumps(error_envelope, indent=2))

    print(f"\n--- full trace ({len(core.trace)} envelopes) ---")
    for msg in core.trace:
        print(f"{msg['message_type']:>7} | {msg['message_id']} | corr={msg['correlation_id']}")


if __name__ == "__main__":
    main()
