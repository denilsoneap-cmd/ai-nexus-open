import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus.adapters.ollama import OllamaError, call_ollama, make_ollama_agent
from nexus.core import NexusCore


def _start_fake_ollama(response_body: dict, status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            self.server.last_request = {"body": body}  # type: ignore[attr-defined]
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
def fake_ollama():
    servers = []

    def _make(response_body: dict, status: int = 200):
        server = _start_fake_ollama(response_body, status)
        servers.append(server)
        url = f"http://127.0.0.1:{server.server_address[1]}/api/chat"
        return url, server

    yield _make
    for s in servers:
        s.shutdown()


def test_call_ollama_returns_parsed_json(fake_ollama):
    url, server = fake_ollama({
        "model": "llama3.2",
        "message": {"role": "assistant", "content": "hello there"},
        "prompt_eval_count": 5,
        "eval_count": 2,
    })
    response = call_ollama("say hi", api_url=url)
    assert response["message"]["content"] == "hello there"
    assert server.last_request["body"]["messages"] == [{"role": "user", "content": "say hi"}]
    assert server.last_request["body"]["stream"] is False


def test_call_ollama_raises_on_http_error(fake_ollama):
    url, _ = fake_ollama({"error": "model not found"}, status=404)
    with pytest.raises(OllamaError):
        call_ollama("say hi", api_url=url)


def test_call_ollama_raises_on_unreachable_host():
    with pytest.raises(OllamaError):
        call_ollama("say hi", api_url="http://127.0.0.1:1/api/chat", timeout=1.0)


def test_call_ollama_handles_missing_message(fake_ollama):
    url, _ = fake_ollama({"model": "llama3.2"})
    core = NexusCore()
    core.register(make_ollama_agent("Ollama", api_url=url))
    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["payload"]["output"]["text"] == ""


def test_make_ollama_agent_routes_through_nexus_core(fake_ollama):
    url, _ = fake_ollama({
        "model": "llama3.2",
        "message": {"role": "assistant", "content": "42"},
        "prompt_eval_count": 3,
        "eval_count": 1,
    })
    core = NexusCore()
    core.register(make_ollama_agent("Ollama", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "what is 6*7?"})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"]["text"] == "42"
    assert result_envelope["payload"]["output"]["usage"] == {"prompt_eval_count": 3, "eval_count": 1}


def test_missing_prompt_is_rejected(fake_ollama):
    url, _ = fake_ollama({"message": {"content": "unused"}})
    core = NexusCore()
    core.register(make_ollama_agent("Ollama", api_url=url))

    result_envelope = core.route("generate_text", input={})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_prompt"


def test_api_error_is_reported_as_retryable(fake_ollama):
    url, _ = fake_ollama({"error": "server busy"}, status=500)
    core = NexusCore()
    core.register(make_ollama_agent("Ollama", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "ollama_api_error"
    assert result_envelope["payload"]["retryable"] is True
