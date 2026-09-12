import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus.adapters.n8n import N8nAdapter, make_n8n_agent
from nexus.core import NexusCore
from nexus.protocol import ErrorPayload, Result, Task


def _start_fake_webhook(response_body: dict, status: int = 200):
    """A real local HTTP server standing in for an n8n webhook — no mocking
    of the adapter itself, just the network endpoint it talks to."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib API name
            length = int(self.headers["Content-Length"])
            self.received_body = self.rfile.read(length)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_body).encode("utf-8"))

        def log_message(self, *args):  # silence test output
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def fake_webhook():
    servers: list[HTTPServer] = []

    def _make(response_body: dict, status: int = 200) -> str:
        server = _start_fake_webhook(response_body, status)
        servers.append(server)
        port = server.server_address[1]
        return f"http://127.0.0.1:{port}/webhook"

    yield _make
    for s in servers:
        s.shutdown()


def test_send_task_returns_result_on_success(fake_webhook):
    url = fake_webhook({"status": "success", "output": {"sent": True}})
    adapter = N8nAdapter(url)
    task = Task(id="task-1", objective="send_invoice_email", input={"to": "a@b.com"})
    outcome = adapter.send_task(task)
    assert isinstance(outcome, Result)
    assert outcome.output == {"sent": True}
    assert outcome.task_id == "task-1"


def test_send_task_returns_error_when_webhook_reports_error(fake_webhook):
    url = fake_webhook({"error_code": "smtp_down", "message": "SMTP relay unreachable"})
    adapter = N8nAdapter(url)
    task = Task(id="task-2", objective="send_invoice_email")
    outcome = adapter.send_task(task)
    assert isinstance(outcome, ErrorPayload)
    assert outcome.error_code == "smtp_down"


def test_send_task_handles_unreachable_host():
    adapter = N8nAdapter("http://127.0.0.1:1/webhook", timeout=1.0)
    task = Task(id="task-3", objective="anything")
    outcome = adapter.send_task(task)
    assert isinstance(outcome, ErrorPayload)
    assert outcome.error_code == "n8n_unreachable"
    assert outcome.retryable is True


def test_make_n8n_agent_routes_through_nexus_core(fake_webhook):
    url = fake_webhook({"status": "success", "output": {"sent": True}})
    core = NexusCore()
    agent = make_n8n_agent("Email Workflow", {"send_invoice_email": url})
    core.register(agent)

    result_envelope = core.route("send_invoice_email", input={"to": "a@b.com"})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"] == {"sent": True}


def test_make_n8n_agent_surfaces_business_error_as_error_envelope(fake_webhook):
    url = fake_webhook({"error_code": "smtp_down", "message": "SMTP relay unreachable"})
    core = NexusCore()
    agent = make_n8n_agent("Email Workflow", {"send_invoice_email": url})
    core.register(agent)

    error_envelope = core.route("send_invoice_email", input={"to": "a@b.com"})
    assert error_envelope["message_type"] == "error"
    assert error_envelope["payload"]["error_code"] == "smtp_down"
