from nexus.adapters.graph import GraphStore
from nexus.agent import Agent
from nexus.core import NexusCore
from nexus.protocol import Task


def test_add_edge_and_query_both_directions():
    graph = GraphStore()
    edge_id = graph.add_edge("task:1", "agent:a", "routed_to", confidence=0.8)
    assert edge_id.startswith("edge-")
    assert [e["relation"] for e in graph.edges_from("task:1")] == ["routed_to"]
    assert [e["source_id"] for e in graph.edges_to("agent:a")] == ["task:1"]


def test_metadata_round_trips_as_dict():
    graph = GraphStore()
    graph.add_edge("task:1", "evidence:1", "supported_by", metadata={"claim": "x"})
    edge = graph.edges_from("task:1")[0]
    assert edge["metadata"] == {"claim": "x"}


def test_nexus_core_records_task_agent_and_evidence_edges():
    graph = GraphStore()
    core = NexusCore(graph=graph)
    agent = Agent(name="Tax Specialist", capabilities=["tax_analysis"])

    @agent.task("analyze_tax")
    def analyze(task: Task):
        ev = agent.make_evidence(
            claim="rate is 18%", source="official.gov.br",
            transformation="extracted_verbatim", confidence=0.97,
        )
        from nexus.protocol import Result
        return Result(task_id=task.id, status="success", output={"tax_rate": 0.18}, evidence=[ev])

    core.register(agent)
    result_envelope = core.route("analyze_tax", task_id="task-graph-1")

    task_node = "task:task-graph-1"
    relations = [e["relation"] for e in graph.edges_from(task_node)]
    assert "supported_by" in relations
    assert any(e["relation"] == "routed_to" for e in graph.edges_from(task_node))
    assert any(e["relation"] == "produced_result" for e in graph.edges_to(task_node))
    assert result_envelope["message_type"] == "result"


def test_nexus_core_without_graph_does_not_error():
    core = NexusCore()  # graph=None
    agent = Agent(name="A", capabilities=["x"])

    @agent.task("op")
    def handler(task: Task):
        return {"ok": True}

    core.register(agent)
    result_envelope = core.route("op")
    assert result_envelope["payload"]["output"]["ok"] is True
