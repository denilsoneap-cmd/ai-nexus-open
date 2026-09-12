import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus.adapters.anthropic import AnthropicError, call_anthropic, make_anthropic_agent
from nexus.core import NexusCore


def _start_fake_anthropic(response_body: dict, status: int = 200, expect_header: dict | None = None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            self.server.last_request = {"body": body, "headers": dict(self.headers)}  # type: ignore[attr-defined]
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_body).encode("utf-8"))

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.last_request = None  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def fake_anthropic():
    servers = []

    def _make(response_body: dict, status: int = 200):
        server = _start_fake_anthropic(response_body, status)
        servers.append(server)
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/messages"
        return url, server

    yield _make
    for s in servers:
        s.shutdown()


def test_call_anthropic_returns_parsed_json(fake_anthropic):
    url, server = fake_anthropic({
        "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "text", "text": "hello there"}],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    })
    response = call_anthropic("say hi", api_key="sk-test", api_url=url)
    assert response["content"][0]["text"] == "hello there"
    assert server.last_request["headers"]["X-Api-Key"] == "sk-test"
    assert server.last_request["body"]["messages"] == [{"role": "user", "content": "say hi"}]


def test_call_anthropic_raises_on_http_error(fake_anthropic):
    url, _ = fake_anthropic({"error": {"message": "bad request"}}, status=400)
    with pytest.raises(AnthropicError):
        call_anthropic("say hi", api_key="sk-test", api_url=url)


def test_call_anthropic_raises_on_unreachable_host():
    with pytest.raises(AnthropicError):
        call_anthropic("say hi", api_key="sk-test", api_url="http://127.0.0.1:1/v1/messages", timeout=1.0)


def test_make_anthropic_agent_routes_through_nexus_core(fake_anthropic):
    url, _ = fake_anthropic({
        "model": "claude-haiku-4-5-20251001",
        "content": [{"type": "text", "text": "42"}],
        "usage": {"input_tokens": 3, "output_tokens": 1},
    })
    core = NexusCore()
    core.register(make_anthropic_agent("Claude", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "what is 6*7?"})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"]["text"] == "42"


def test_missing_api_key_fails_without_calling_the_network(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # don't let a real env var make this flaky
    core = NexusCore()
    agent = make_anthropic_agent("Claude", api_key=None)
    core.register(agent)

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_api_key"


def test_missing_prompt_is_rejected(fake_anthropic):
    url, _ = fake_anthropic({"content": [{"type": "text", "text": "unused"}]})
    core = NexusCore()
    core.register(make_anthropic_agent("Claude", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_prompt"


def test_api_error_is_reported_as_retryable(fake_anthropic):
    url, _ = fake_anthropic({"error": {"message": "overloaded"}}, status=529)
    core = NexusCore()
    core.register(make_anthropic_agent("Claude", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "anthropic_api_error"
    assert result_envelope["payload"]["retryable"] is True
