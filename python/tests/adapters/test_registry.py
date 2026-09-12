import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus.adapters.registry import check_npm, check_pypi, compare_versions, make_registry_agent
from nexus.core import NexusCore


def _start_fake_registry(routes: dict[str, dict]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = routes.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def fake_registry():
    servers = []

    def _make(routes: dict[str, dict]) -> str:
        server = _start_fake_registry(routes)
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield _make
    for s in servers:
        s.shutdown()


def test_check_npm_returns_latest_version(fake_registry):
    url = fake_registry({
        "/nexus-sdk": {
            "versions": {"0.1.0": {}, "0.2.0": {}},
            "dist-tags": {"latest": "0.2.0"},
            "homepage": "https://example.com",
            "description": "test package",
        }
    })
    result = check_npm("nexus-sdk", registry_url=url)
    assert result["latest"] == "0.2.0"
    assert result["registry"] == "npm"


def test_check_npm_handles_missing_package(fake_registry):
    url = fake_registry({})
    result = check_npm("does-not-exist", registry_url=url)
    assert "error" in result


def test_check_pypi_returns_latest_version(fake_registry):
    url = fake_registry({
        "/nexus-sdk/json": {
            "info": {"version": "0.1.0", "home_page": "https://example.com", "summary": "test"},
            "releases": {"0.1.0": []},
        }
    })
    result = check_pypi("nexus-sdk", registry_url=url)
    assert result["latest"] == "0.1.0"
    assert result["registry"] == "pypi"


def test_compare_versions_flags_outdated():
    result = compare_versions("0.1.0", "0.2.0")
    assert result["is_outdated"] is True
    assert "Update from" in result["recommendation"]


def test_compare_versions_flags_up_to_date():
    result = compare_versions("0.2.0", "0.2.0")
    assert result["is_outdated"] is False


def test_compare_versions_handles_missing_latest():
    result = compare_versions("0.1.0", None)
    assert "error" in result


def test_registry_agent_routes_through_nexus_core(fake_registry):
    url = fake_registry({
        "/nexus-sdk": {"versions": {"0.1.0": {}}, "dist-tags": {"latest": "0.1.0"}},
    })
    core = NexusCore()
    core.register(make_registry_agent(npm_url=url))

    result_envelope = core.route("check_npm_version", input={"package": "nexus-sdk"})
    assert result_envelope["payload"]["output"]["latest"] == "0.1.0"
