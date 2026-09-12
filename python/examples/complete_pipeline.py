"""Runs every optional NexusCore dependency at once — graph, audit, trust,
arbitration, and policy — to demonstrate (and regression-check) that they
compose without conflict, since each was built and tested independently
(RFC-0003 through RFC-0006).

    python examples/complete_pipeline.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus import Agent, NexusCore, Result  # noqa: E402
from nexus.adapters.graph import GraphStore  # noqa: E402
from nexus.arbitration import ArbitrationEngine  # noqa: E402
from nexus.audit import AuditLog  # noqa: E402
from nexus.policy import PolicyEngine  # noqa: E402
from nexus.trust import TrustEvaluator  # noqa: E402


def build_core() -> NexusCore:
    return NexusCore(
        graph=GraphStore(),
        audit=AuditLog(),
        trust=TrustEvaluator(),
        arbiter=ArbitrationEngine(),
        # A real deployment would prompt a human here; this always approves,
        # standing in for that decision (see nexus.policy's module docstring).
        policy=PolicyEngine(approver=lambda task, decision: True),
    )


def main() -> None:
    core = build_core()

    careful_agent = Agent(name="Careful Tax Specialist", capabilities=["analyze"])

    @careful_agent.task("analyze")
    def careful_analyze(task) -> Result:
        evidence = careful_agent.make_evidence(
            claim="The ICMS-ST rate for this product in MG is 18%.",
            source="official.gov.br",
            transformation="extracted_verbatim",
            confidence=0.97,
        )
        return Result(task_id=task.id, output={"tax_rate": 0.18}, evidence=[evidence])

    core.register(careful_agent)

    print("--- route(): risk=critical, gated by policy, approved ---")
    result_envelope = core.route("analyze", input={"jurisdiction": "MG"}, risk="critical")
    print(f"  {result_envelope['message_type']}: {result_envelope['payload']['output']}")

    print("\n--- audit log: tamper-evident chain over both the task and its result ---")
    print(f"  {len(core.audit.events())} events, verify() = {core.audit.verify()}")

    print("\n--- graph: what got recorded for this task ---")
    task_id = result_envelope["payload"]["task_id"]
    for edge in core.graph.edges_from(f"task:{task_id}"):
        print(f"  task:{task_id} --{edge['relation']}--> {edge['target_id']}")

    print("\n--- debate(): a second, careless agent disagrees with no evidence ---")
    careless_agent = Agent(name="Careless Guesser", capabilities=["analyze"])

    @careless_agent.task("analyze")
    def careless_analyze(task) -> Result:
        return Result(task_id=task.id, output={"tax_rate": 0.0})  # confidently wrong, no evidence

    core.register(careless_agent)
    verdict = core.debate("analyze", input={"jurisdiction": "MG"})
    print(f"  winner: {verdict.winner_agent_id}")
    print(f"  reasoning: {verdict.reasoning}")

    print("\n--- route(): risk=critical, but this policy has no approver — fails closed ---")
    locked_down_core = NexusCore(policy=PolicyEngine())  # no approver configured
    locked_down_core.register(careful_agent)
    blocked_envelope = locked_down_core.route("analyze", risk="critical")
    print(f"  {blocked_envelope['message_type']}: {blocked_envelope['payload']}")


if __name__ == "__main__":
    main()
