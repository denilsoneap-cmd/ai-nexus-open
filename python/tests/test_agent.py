import pytest

from nexus.agent import Agent, CapabilityUnavailable
from nexus.protocol import ProtocolError, Result, Task


def make_tax_agent() -> Agent:
    agent = Agent(name="Tax Specialist", capabilities=["tax_analysis"])

    @agent.task("analyze_tax")
    def analyze(task: Task) -> dict:
        return {"tax_rate": 0.18, "jurisdiction": task.input.get("jurisdiction")}

    return agent


def test_agent_handles_registered_objective():
    agent = make_tax_agent()
    task = Task(id="task-1", objective="analyze_tax", input={"jurisdiction": "MG"})
    result = agent.handle(task)
    assert isinstance(result, Result)
    assert result.status == "success"
    assert result.output["tax_rate"] == 0.18
    assert result.task_id == "task-1"


def test_agent_raises_for_unregistered_objective():
    agent = make_tax_agent()
    task = Task(id="task-1", objective="translate_document")
    with pytest.raises(CapabilityUnavailable):
        agent.handle(task)


def test_handler_returning_result_directly():
    agent = Agent(name="Custom", capabilities=["custom"])

    @agent.task("custom_op")
    def handler(task: Task) -> Result:
        return Result(task_id=task.id, status="partial", output={"note": "in progress"})

    result = agent.handle(Task(id="task-2", objective="custom_op"))
    assert result.status == "partial"


def test_handler_result_with_mismatched_task_id_is_rejected():
    agent = Agent(name="Broken", capabilities=[])

    @agent.task("op")
    def handler(task: Task) -> Result:
        return Result(task_id="wrong-id", status="success")

    with pytest.raises(ProtocolError):
        agent.handle(Task(id="task-3", objective="op"))


def test_handler_must_return_dict_or_result():
    agent = Agent(name="Broken", capabilities=[])

    @agent.task("op")
    def handler(task: Task) -> str:
        return "not allowed"

    with pytest.raises(ProtocolError):
        agent.handle(Task(id="task-4", objective="op"))


def test_make_evidence_attributes_to_self():
    agent = make_tax_agent()
    ev = agent.make_evidence(
        claim="Rate is 18%", source="official.gov.br",
        transformation="extracted_verbatim", confidence=0.97,
    )
    assert ev.agent_id == agent.identity.agent_id


def test_refuse_and_fail_helpers():
    agent = make_tax_agent()
    task = Task(id="task-5", objective="analyze_tax")

    refusal = agent.refuse(task, reason="out of jurisdiction")
    assert refusal.status == "refused"

    failure = agent.fail(task, error_code="internal_error", message="boom")
    assert failure.error_code == "internal_error"
