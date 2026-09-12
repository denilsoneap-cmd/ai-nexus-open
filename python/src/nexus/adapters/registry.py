"""Level 3 (Model Universe) / Developer Platform — checks a package's latest
version on PyPI or npm, so a Model Registry entry (or any dependency
reference an agent relies on) can be flagged as outdated instead of quietly
going stale.

Pattern lifted from this project's own `mcp-tools/context7-mcp/index.js`
(a small Node.js tool doing the same npm/PyPI lookup): reimplemented here in
pure Python (`urllib`, stdlib only, no `axios`) since Nexus's adapters are
Python — the `checkNPM`/`checkPyPI`/`compareVersions` shape is what's
ported, not the JS code itself.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..agent import Agent
from ..protocol import Task

NPM_REGISTRY = "https://registry.npmjs.org"
PYPI_REGISTRY = "https://pypi.org/pypi"


def _fetch_json(url: str, timeout: float) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def check_npm(package_name: str, registry_url: str = NPM_REGISTRY, timeout: float = 10.0) -> dict[str, Any]:
    data = _fetch_json(f"{registry_url}/{package_name}", timeout)
    if data is None:
        return {"error": f"package not found or registry unreachable: {package_name!r}", "registry": "npm"}
    versions = list(data.get("versions", {}).keys())
    return {
        "name": package_name,
        "registry": "npm",
        "latest": data.get("dist-tags", {}).get("latest"),
        "versions": versions[-10:],
        "homepage": data.get("homepage"),
        "description": data.get("description"),
    }


def check_pypi(package_name: str, registry_url: str = PYPI_REGISTRY, timeout: float = 10.0) -> dict[str, Any]:
    data = _fetch_json(f"{registry_url}/{package_name}/json", timeout)
    if data is None:
        return {"error": f"package not found or registry unreachable: {package_name!r}", "registry": "pypi"}
    info = data.get("info", {})
    releases = list(data.get("releases", {}).keys())
    return {
        "name": package_name,
        "registry": "pypi",
        "latest": info.get("version"),
        "versions": releases[-10:],
        "homepage": info.get("home_page"),
        "description": info.get("summary"),
    }


def compare_versions(current_version: str, latest_version: str | None) -> dict[str, Any]:
    if latest_version is None:
        return {"error": "no latest version available for comparison"}
    is_outdated = current_version != latest_version
    return {
        "current": current_version,
        "latest": latest_version,
        "is_outdated": is_outdated,
        "recommendation": (
            f"Update from {current_version} to {latest_version}" if is_outdated else "Up to date"
        ),
    }


def make_registry_agent(
    name: str = "Registry Freshness",
    npm_url: str = NPM_REGISTRY,
    pypi_url: str = PYPI_REGISTRY,
) -> Agent:
    agent = Agent(name=name, capabilities=["check_npm_version", "check_pypi_version"])

    @agent.task("check_npm_version")
    def _check_npm(task: Task) -> dict[str, Any]:
        return check_npm(task.input["package"], registry_url=npm_url)

    @agent.task("check_pypi_version")
    def _check_pypi(task: Task) -> dict[str, Any]:
        return check_pypi(task.input["package"], registry_url=pypi_url)

    return agent
