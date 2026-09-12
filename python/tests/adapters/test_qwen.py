import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus.adapters.qwen import QwenError, call_qwen, make_qwen_agent
from nexus.core import NexusCore


def _start_fake_qwen(response_body: dict, status: int = 200):
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
def fake_qwen():
    servers = []

    def _make(response_body: dict, status: int = 200):
        server = _start_fake_qwen(response_body, status)
        servers.append(server)
        url = f"http://127.0.0.1:{server.server_address[1]}/compatible-mode/v1/chat/completions"
        return url, server

    yield _make
    for s in servers:
        s.shutdown()


def test_call_qwen_returns_parsed_json(fake_qwen):
    url, server = fake_qwen({
        "model": "qwen-turbo",
        "choices": [{"message": {"role": "assistant", "content": "hello there"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    })
    response = call_qwen("say hi", api_key="sk-test", api_url=url)
    assert response["choices"][0]["message"]["content"] == "hello there"
    assert server.last_request["headers"]["Authorization"] == "Bearer sk-test"
    assert server.last_request["body"]["messages"] == [{"role": "user", "content": "say hi"}]


def test_call_qwen_raises_on_http_error(fake_qwen):
    url, _ = fake_qwen({"error": {"message": "bad request"}}, status=400)
    with pytest.raises(QwenError):
        call_qwen("say hi", api_key="sk-test", api_url=url)


def test_call_qwen_raises_on_unreachable_host():
    with pytest.raises(QwenError):
        call_qwen("say hi", api_key="sk-test", api_url="http://127.0.0.1:1/compatible-mode/v1/chat/completions", timeout=1.0)


def test_call_qwen_handles_empty_choices(fake_qwen):
    url, _ = fake_qwen({"model": "qwen-turbo", "choices": []})
    core = NexusCore()
    core.register(make_qwen_agent("Qwen", api_key="sk-test", api_url=url))
    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["payload"]["output"]["text"] == ""


def test_make_qwen_agent_routes_through_nexus_core(fake_qwen):
    url, _ = fake_qwen({
        "model": "qwen-turbo",
        "choices": [{"message": {"role": "assistant", "content": "42"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    })
    core = NexusCore()
    core.register(make_qwen_agent("Qwen", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "what is 6*7?"})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"]["text"] == "42"


def test_missing_api_key_fails_without_calling_the_network(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    core = NexusCore()
    core.register(make_qwen_agent("Qwen", api_key=None))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_api_key"


def test_missing_prompt_is_rejected(fake_qwen):
    url, _ = fake_qwen({"choices": [{"message": {"content": "unused"}}]})
    core = NexusCore()
    core.register(make_qwen_agent("Qwen", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_prompt"


def test_api_error_is_reported_as_retryable(fake_qwen):
    url, _ = fake_qwen({"error": {"message": "rate limited"}}, status=429)
    core = NexusCore()
    core.register(make_qwen_agent("Qwen", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "qwen_api_error"
    assert result_envelope["payload"]["retryable"] is True
