import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus.adapters.hunyuan import HunyuanError, call_hunyuan, make_hunyuan_agent
from nexus.core import NexusCore


def _start_fake_hunyuan(response_body: dict, status: int = 200):
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
def fake_hunyuan():
    servers = []

    def _make(response_body: dict, status: int = 200):
        server = _start_fake_hunyuan(response_body, status)
        servers.append(server)
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
        return url, server

    yield _make
    for s in servers:
        s.shutdown()


def test_call_hunyuan_returns_parsed_json(fake_hunyuan):
    url, server = fake_hunyuan({
        "model": "hunyuan-lite",
        "choices": [{"message": {"role": "assistant", "content": "hello there"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    })
    response = call_hunyuan("say hi", api_key="sk-test", api_url=url)
    assert response["choices"][0]["message"]["content"] == "hello there"
    assert server.last_request["headers"]["Authorization"] == "Bearer sk-test"
    assert server.last_request["body"]["messages"] == [{"role": "user", "content": "say hi"}]


def test_call_hunyuan_raises_on_http_error(fake_hunyuan):
    url, _ = fake_hunyuan({"error": {"message": "bad request"}}, status=400)
    with pytest.raises(HunyuanError):
        call_hunyuan("say hi", api_key="sk-test", api_url=url)


def test_call_hunyuan_raises_on_unreachable_host():
    with pytest.raises(HunyuanError):
        call_hunyuan("say hi", api_key="sk-test", api_url="http://127.0.0.1:1/v1/chat/completions", timeout=1.0)


def test_call_hunyuan_handles_empty_choices(fake_hunyuan):
    url, _ = fake_hunyuan({"model": "hunyuan-lite", "choices": []})
    core = NexusCore()
    core.register(make_hunyuan_agent("Hunyuan", api_key="sk-test", api_url=url))
    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["payload"]["output"]["text"] == ""


def test_make_hunyuan_agent_routes_through_nexus_core(fake_hunyuan):
    url, _ = fake_hunyuan({
        "model": "hunyuan-lite",
        "choices": [{"message": {"role": "assistant", "content": "42"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    })
    core = NexusCore()
    core.register(make_hunyuan_agent("Hunyuan", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "what is 6*7?"})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"]["text"] == "42"


def test_missing_api_key_fails_without_calling_the_network(monkeypatch):
    monkeypatch.delenv("HUNYUAN_API_KEY", raising=False)
    core = NexusCore()
    core.register(make_hunyuan_agent("Hunyuan", api_key=None))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_api_key"


def test_missing_prompt_is_rejected(fake_hunyuan):
    url, _ = fake_hunyuan({"choices": [{"message": {"content": "unused"}}]})
    core = NexusCore()
    core.register(make_hunyuan_agent("Hunyuan", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_prompt"


def test_api_error_is_reported_as_retryable(fake_hunyuan):
    url, _ = fake_hunyuan({"error": {"message": "rate limited"}}, status=429)
    core = NexusCore()
    core.register(make_hunyuan_agent("Hunyuan", api_key="sk-test", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "hunyuan_api_error"
    assert result_envelope["payload"]["retryable"] is True
