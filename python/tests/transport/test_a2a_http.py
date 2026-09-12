import asyncio
import socket
import threading
import time

import pytest

uvicorn = pytest.importorskip("uvicorn", reason="a2a-sdk's server extra (uvicorn) is not installed")

from nexus.agent import Agent
from nexus.core import NexusCore
from nexus.discovery import InMemoryRegistry, publish_agent
from nexus.protocol import ErrorPayload, Result, Task
from nexus.transport.a2a_http import A2ATransportError, build_agent_card, build_app, call_remote_agent, dispatch_via_card


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(core: NexusCore, objectives: list[str]):
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    card = build_agent_card("Test Nexus Server", base_url, objectives)
    app = build_app(core, card)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()

    deadline = time.monotonic() + 10.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("test A2A server did not start in time")

    return server, base_url


@pytest.fixture
def a2a_server():
    servers = []

    def _make(core: NexusCore, objectives: list[str]) -> str:
        server, base_url = _start_server(core, objectives)
        servers.append(server)
        return base_url

    yield _make
    for server in servers:
        server.should_exit = True
    time.sleep(0.2)  # let servers actually stop before the next test grabs a port


def _core_with_tax_agent() -> NexusCore:
    core = NexusCore()
    agent = Agent(name="Tax Specialist", capabilities=["analyze_tax"])

    @agent.task("analyze_tax")
    def analyze(task: Task) -> dict:
        return {"tax_rate": 0.18, "jurisdiction": task.input.get("jurisdiction")}

    core.register(agent)
    return core


def test_call_remote_agent_returns_a_real_result_over_http(a2a_server):
    base_url = a2a_server(_core_with_tax_agent(), ["analyze_tax"])

    result = asyncio.run(call_remote_agent(base_url, "analyze_tax", {"jurisdiction": "MG"}))

    assert result["message_type"] == "result"
    assert result["payload"]["output"] == {"tax_rate": 0.18, "jurisdiction": "MG"}


def test_call_remote_agent_returns_a_real_error_envelope_for_unknown_objective(a2a_server):
    base_url = a2a_server(NexusCore(), ["some_objective"])  # no agent registered at all

    result = asyncio.run(call_remote_agent(base_url, "some_objective", {}))

    assert result["message_type"] == "error"
    assert result["payload"]["error_code"] == "capability_unavailable"


def test_call_remote_agent_raises_transport_error_for_unreachable_server():
    with pytest.raises(A2ATransportError):
        asyncio.run(call_remote_agent("http://127.0.0.1:1", "anything", {}, timeout=2.0))


def test_call_remote_agent_works_without_input(a2a_server):
    core = NexusCore()
    agent = Agent(name="Pinger", capabilities=["ping"])

    @agent.task("ping")
    def ping(task: Task) -> dict:
        return {"pong": True}

    core.register(agent)
    base_url = a2a_server(core, ["ping"])

    result = asyncio.run(call_remote_agent(base_url, "ping"))
    assert result["payload"]["output"] == {"pong": True}


def test_build_agent_card_has_one_skill_per_objective():
    card = build_agent_card("My Server", "http://127.0.0.1:9999", ["a", "b", "c"])
    assert [skill.id for skill in card.skills] == ["a", "b", "c"]


def test_two_servers_do_not_interfere_with_each_other(a2a_server):
    core_a = NexusCore()
    agent_a = Agent(name="A", capabilities=["op_a"])

    @agent_a.task("op_a")
    def handle_a(task: Task) -> dict:
        return {"handled_by": "a"}

    core_a.register(agent_a)

    core_b = NexusCore()
    agent_b = Agent(name="B", capabilities=["op_b"])

    @agent_b.task("op_b")
    def handle_b(task: Task) -> dict:
        return {"handled_by": "b"}

    core_b.register(agent_b)

    url_a = a2a_server(core_a, ["op_a"])
    url_b = a2a_server(core_b, ["op_b"])

    result_a = asyncio.run(call_remote_agent(url_a, "op_a"))
    result_b = asyncio.run(call_remote_agent(url_b, "op_b"))
    assert result_a["payload"]["output"]["handled_by"] == "a"
    assert result_b["payload"]["output"]["handled_by"] == "b"


def test_dispatch_via_card_closes_the_discovery_to_dispatch_gap(a2a_server):
    """The real end-to-end path RFC-0007 §5 left open: publish an agent to
    a registry with a real url, discover it back (a fresh dict, no
    in-process reference to the original Agent survives this), and
    dispatch to it — getting a real Result, not just proof the card
    exists."""
    core = _core_with_tax_agent()
    agent = core.agents()[0]
    base_url = a2a_server(core, ["analyze_tax"])

    registry = InMemoryRegistry()
    publish_agent(registry, agent, url=base_url)
    discovered_card = registry.get(agent.identity.agent_id)

    outcome = asyncio.run(dispatch_via_card(discovered_card, "analyze_tax", {"jurisdiction": "MG"}))

    assert isinstance(outcome, Result)
    assert outcome.output == {"tax_rate": 0.18, "jurisdiction": "MG"}


def test_dispatch_via_card_returns_error_payload_for_a_remote_error(a2a_server):
    base_url = a2a_server(NexusCore(), ["some_objective"])  # no agent registered
    card = {"id": "agent:whoever", "url": base_url}

    outcome = asyncio.run(dispatch_via_card(card, "some_objective", {}))

    assert isinstance(outcome, ErrorPayload)
    assert outcome.error_code == "capability_unavailable"


def test_dispatch_via_card_raises_when_card_has_no_url():
    card = {"id": "agent:no-url"}
    with pytest.raises(A2ATransportError):
        asyncio.run(dispatch_via_card(card, "anything", {}))
