import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus.adapters.llamacpp import LlamaCppError, call_llamacpp, make_llamacpp_agent
from nexus.core import NexusCore


def _start_fake_llamacpp(response_body: dict, status: int = 200):
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
def fake_llamacpp():
    servers = []

    def _make(response_body: dict, status: int = 200):
        server = _start_fake_llamacpp(response_body, status)
        servers.append(server)
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
        return url, server

    yield _make
    for s in servers:
        s.shutdown()


def test_call_llamacpp_returns_parsed_json_without_api_key(fake_llamacpp):
    url, server = fake_llamacpp({
        "model": "local-model.gguf",
        "choices": [{"message": {"role": "assistant", "content": "hello there"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    })
    response = call_llamacpp("say hi", model="local-model.gguf", api_url=url)
    assert response["choices"][0]["message"]["content"] == "hello there"
    assert "Authorization" not in server.last_request["headers"]
    assert server.last_request["body"]["messages"] == [{"role": "user", "content": "say hi"}]


def test_call_llamacpp_sends_authorization_when_api_key_given(fake_llamacpp):
    url, server = fake_llamacpp({
        "model": "m",
        "choices": [{"message": {"role": "assistant", "content": "hi"}}],
    })
    call_llamacpp("say hi", model="m", api_key="secret", api_url=url)
    assert server.last_request["headers"]["Authorization"] == "Bearer secret"


def test_call_llamacpp_raises_on_http_error(fake_llamacpp):
    url, _ = fake_llamacpp({"error": {"message": "bad request"}}, status=400)
    with pytest.raises(LlamaCppError):
        call_llamacpp("say hi", model="m", api_url=url)


def test_call_llamacpp_raises_on_unreachable_host():
    with pytest.raises(LlamaCppError):
        call_llamacpp("say hi", model="m", api_url="http://127.0.0.1:1/v1/chat/completions", timeout=1.0)


def test_call_llamacpp_handles_empty_choices(fake_llamacpp):
    url, _ = fake_llamacpp({"model": "m", "choices": []})
    core = NexusCore()
    core.register(make_llamacpp_agent("LlamaCpp", model="m", api_url=url))
    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["payload"]["output"]["text"] == ""


def test_make_llamacpp_agent_routes_through_nexus_core(fake_llamacpp):
    url, _ = fake_llamacpp({
        "model": "m",
        "choices": [{"message": {"role": "assistant", "content": "42"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    })
    core = NexusCore()
    core.register(make_llamacpp_agent("LlamaCpp", model="m", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "what is 6*7?"})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"]["text"] == "42"


def test_missing_prompt_is_rejected(fake_llamacpp):
    url, _ = fake_llamacpp({"choices": [{"message": {"content": "unused"}}]})
    core = NexusCore()
    core.register(make_llamacpp_agent("LlamaCpp", model="m", api_url=url))

    result_envelope = core.route("generate_text", input={})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_prompt"


def test_api_error_is_reported_as_retryable(fake_llamacpp):
    url, _ = fake_llamacpp({"error": {"message": "rate limited"}}, status=429)
    core = NexusCore()
    core.register(make_llamacpp_agent("LlamaCpp", model="m", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "llamacpp_api_error"
    assert result_envelope["payload"]["retryable"] is True
