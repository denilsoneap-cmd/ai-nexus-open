from nexus.adapters.graph import GraphStore
from nexus.agent import Agent
from nexus.arbitration import ArbitrationEngine
from nexus.core import NexusCore
from nexus.protocol import Result, Task


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


def test_edges_by_relation_filters_to_that_relation_only():
    graph = GraphStore()
    graph.add_edge("task:1", "agent:a", "routed_to")
    graph.add_edge("task:1", "agent:b", "routed_to")
    graph.add_edge("task:1", "agent:a", "won")
    assert {e["target_id"] for e in graph.edges_by_relation("routed_to")} == {"agent:a", "agent:b"}
    assert [e["target_id"] for e in graph.edges_by_relation("won")] == ["agent:a"]


def test_edges_by_relation_returns_empty_for_unused_relation():
    graph = GraphStore()
    graph.add_edge("task:1", "agent:a", "routed_to")
    assert graph.edges_by_relation("won") == []


def test_edges_by_relation_respects_limit():
    graph = GraphStore()
    for i in range(5):
        graph.add_edge(f"task:{i}", "agent:a", "won")
    assert len(graph.edges_by_relation("won", limit=2)) == 2


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


def test_debate_records_routed_to_produced_result_and_supported_by_edges():
    graph = GraphStore()
    core = NexusCore(graph=graph, arbiter=ArbitrationEngine())

    weak = Agent(name="Weak", capabilities=["classify"])
    strong = Agent(name="Strong", capabilities=["classify"])

    @weak.task("classify")
    def weak_handle(task: Task) -> Result:
        ev = weak.make_evidence(claim="x", source="y", transformation="inferred", confidence=0.5)
        return Result(task_id=task.id, output={"label": "spam"}, evidence=[ev])

    @strong.task("classify")
    def strong_handle(task: Task) -> Result:
        ev = strong.make_evidence(claim="x", source="y", transformation="extracted_verbatim", confidence=0.95)
        return Result(task_id=task.id, output={"label": "ham"}, evidence=[ev])

    core.register(weak)
    core.register(strong)

    core.debate("classify", task_id="task-debate-graph-1")

    task_node = "task:task-debate-graph-1"
    routed_to_targets = {e["target_id"] for e in graph.edges_from(task_node) if e["relation"] == "routed_to"}
    assert routed_to_targets == {weak.identity.agent_id, strong.identity.agent_id}
    produced_result_sources = {e["source_id"] for e in graph.edges_to(task_node) if e["relation"] == "produced_result"}
    assert produced_result_sources == {weak.identity.agent_id, strong.identity.agent_id}
    relations = [e["relation"] for e in graph.edges_from(task_node)]
    assert relations.count("supported_by") == 2


def test_debate_records_a_won_edge_for_the_winner_only():
    graph = GraphStore()
    core = NexusCore(graph=graph, arbiter=ArbitrationEngine())

    weak = Agent(name="Weak", capabilities=["classify"])
    strong = Agent(name="Strong", capabilities=["classify"])

    @weak.task("classify")
    def weak_handle(task: Task) -> Result:
        ev = weak.make_evidence(claim="x", source="y", transformation="inferred", confidence=0.5)
        return Result(task_id=task.id, output={"label": "spam"}, evidence=[ev])

    @strong.task("classify")
    def strong_handle(task: Task) -> Result:
        ev = strong.make_evidence(claim="x", source="y", transformation="extracted_verbatim", confidence=0.95)
        return Result(task_id=task.id, output={"label": "ham"}, evidence=[ev])

    core.register(weak)
    core.register(strong)

    verdict = core.debate("classify", task_id="task-debate-won-1")

    task_node = "task:task-debate-won-1"
    won_edges = [e for e in graph.edges_from(task_node) if e["relation"] == "won"]
    assert len(won_edges) == 1
    assert won_edges[0]["target_id"] == verdict.winner_agent_id == strong.identity.agent_id


def test_debate_without_graph_does_not_error():
    core = NexusCore(arbiter=ArbitrationEngine())  # graph=None
    agent = Agent(name="A", capabilities=["op"])

    @agent.task("op")
    def handler(task: Task):
        return {"ok": True}

    core.register(agent)
    verdict = core.debate("op")
    assert verdict.winning_result.output["ok"] is True
