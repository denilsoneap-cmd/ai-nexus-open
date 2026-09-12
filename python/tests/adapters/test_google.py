import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest

from nexus.adapters.google import GoogleError, call_google, make_google_agent
from nexus.core import NexusCore


def _start_fake_google(response_body: dict, status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            self.server.last_request = {  # type: ignore[attr-defined]
                "body": body,
                "path": urlparse(self.path).path,
                "query": urlparse(self.path).query,
            }
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
def fake_google():
    servers = []

    def _make(response_body: dict, status: int = 200):
        server = _start_fake_google(response_body, status)
        servers.append(server)
        url = f"http://127.0.0.1:{server.server_address[1]}/v1beta/models/{{model}}:generateContent"
        return url, server

    yield _make
    for s in servers:
        s.shutdown()


def test_call_google_returns_parsed_json(fake_google):
    url, server = fake_google({
        "modelVersion": "gemini-2.0-flash",
        "candidates": [{"content": {"parts": [{"text": "hello there"}]}}],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
    })
    response = call_google("say hi", api_key="test-key", api_url=url)
    assert response["candidates"][0]["content"]["parts"][0]["text"] == "hello there"
    assert "key=test-key" in server.last_request["query"]
    assert server.last_request["body"]["contents"] == [{"parts": [{"text": "say hi"}]}]


def test_call_google_raises_on_http_error(fake_google):
    url, _ = fake_google({"error": {"message": "bad request"}}, status=400)
    with pytest.raises(GoogleError):
        call_google("say hi", api_key="test-key", api_url=url)


def test_call_google_raises_on_unreachable_host():
    with pytest.raises(GoogleError):
        call_google(
            "say hi", api_key="test-key",
            api_url="http://127.0.0.1:1/v1beta/models/{model}:generateContent", timeout=1.0,
        )


def test_call_google_handles_empty_candidates(fake_google):
    url, _ = fake_google({"modelVersion": "gemini-2.0-flash", "candidates": []})
    core = NexusCore()
    core.register(make_google_agent("Gemini", api_key="test-key", api_url=url))
    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["payload"]["output"]["text"] == ""


def test_make_google_agent_routes_through_nexus_core(fake_google):
    url, _ = fake_google({
        "modelVersion": "gemini-2.0-flash",
        "candidates": [{"content": {"parts": [{"text": "42"}]}}],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
    })
    core = NexusCore()
    core.register(make_google_agent("Gemini", api_key="test-key", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "what is 6*7?"})
    assert result_envelope["message_type"] == "result"
    assert result_envelope["payload"]["output"]["text"] == "42"


def test_missing_api_key_fails_without_calling_the_network(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    core = NexusCore()
    core.register(make_google_agent("Gemini", api_key=None))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_api_key"


def test_missing_prompt_is_rejected(fake_google):
    url, _ = fake_google({"candidates": [{"content": {"parts": [{"text": "unused"}]}}]})
    core = NexusCore()
    core.register(make_google_agent("Gemini", api_key="test-key", api_url=url))

    result_envelope = core.route("generate_text", input={})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "missing_prompt"


def test_api_error_is_reported_as_retryable(fake_google):
    url, _ = fake_google({"error": {"message": "rate limited"}}, status=429)
    core = NexusCore()
    core.register(make_google_agent("Gemini", api_key="test-key", api_url=url))

    result_envelope = core.route("generate_text", input={"prompt": "hi"})
    assert result_envelope["message_type"] == "error"
    assert result_envelope["payload"]["error_code"] == "google_api_error"
    assert result_envelope["payload"]["retryable"] is True
