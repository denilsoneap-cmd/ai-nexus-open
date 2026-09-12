"""Runs every adapter built so far (graph, Obsidian, Superpowers-style skill
agent, and a Tax Specialist agent) through one NexusCore, to show what
routing a task actually touches end to end.

    python examples/full_stack.py

n8n is deliberately left out here — it needs a real webhook to POST to; see
tests/adapters/test_n8n.py for a runnable example against a local fake one.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus import Agent, NexusCore, Result  # noqa: E402
from nexus.adapters.graph import GraphStore  # noqa: E402
from nexus.adapters.obsidian import ObsidianVault  # noqa: E402
from nexus.adapters.superpowers import make_skill_agent  # noqa: E402


def fake_skill_runner(skill_name: str, input: dict) -> dict:
    """Stands in for github.com/obra/superpowers (or Claude Code's own Skill
    tool) actually running a skill — see the module docstring for why Nexus
    takes this as an injected callable instead of calling superpowers directly."""
    return {"skill": skill_name, "ran_with": input}


def main() -> None:
    vault_dir = Path(tempfile.mkdtemp(prefix="nexus-vault-"))
    graph = GraphStore()
    vault = ObsidianVault(vault_dir)
    core = NexusCore(graph=graph)

    tax_agent = Agent(name="Tax Specialist", capabilities=["tax_analysis"])

    @tax_agent.task("analyze_tax")
    def analyze(task):
        evidence = tax_agent.make_evidence(
            claim="The ICMS-ST rate for this product in MG is 18%.",
            source="official.gov.br",
            transformation="extracted_verbatim",
            confidence=0.97,
            location="Article 15",
        )
        vault.write_evidence_note(evidence, task_id=task.id)
        return Result(
            task_id=task.id,
            status="success",
            output={"tax_rate": 0.18},
            confidence=0.94,
            evidence=[evidence],
        )

    dev_agent = make_skill_agent(
        name="Dev Agent",
        skill_map={"write_tests": "test-driven-development"},
        runner=fake_skill_runner,
    )

    core.register(tax_agent)
    core.register(dev_agent)

    print("--- route to Tax Specialist (writes an Obsidian note + graph edges) ---")
    result_envelope = core.route("analyze_tax", input={"jurisdiction": "MG"}, task_id="task-full-1")
    print(f"result status: {result_envelope['payload']['status']}")

    print("\n--- route to Dev Agent (Superpowers-style skill runner) ---")
    skill_envelope = core.route("write_tests", input={"file": "billing.py"}, task_id="task-full-2")
    print(f"skill output: {skill_envelope['payload']['output']}")

    print(f"\n--- Obsidian vault at {vault_dir} ---")
    for note in vault.list_notes():
        print(f"  {note.name}")

    print("\n--- graph edges for task-full-1 ---")
    for edge in graph.edges_from("task:task-full-1"):
        print(f"  {edge['source_id']} --{edge['relation']}--> {edge['target_id']}")
    for edge in graph.edges_to("task:task-full-1"):
        print(f"  {edge['source_id']} --{edge['relation']}--> {edge['target_id']}")


if __name__ == "__main__":
    main()
