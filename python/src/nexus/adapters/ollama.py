"""Level 3 (Model Universe) — wraps a local Ollama server's `/api/chat`
endpoint as a Nexus Agent, using stdlib `urllib` (no `ollama` SDK
dependency). Same `{text, model, usage}` contract as the other Level 3
adapters (ARCHITECTURE.md principle 1), but genuinely different underneath:
no API key (Ollama serves localhost by default), a `num_predict` option
instead of `max_tokens`, and usage reported as Ollama's own duration/count
fields rather than an OpenAI-shaped `usage` object — evidence the adapter
layer covers local, free models just as well as paid cloud ones.

Unlike the paid-API adapters, `call_ollama` *could* be exercised against a
real local server (no cost, no key) — this project's own tests still point
`api_url` at a local fake HTTP server, the same as every other adapter here,
so the suite doesn't depend on Ollama being installed on whatever machine
runs it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task

OLLAMA_API_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3.2"  # small, widely-pulled local model — caller must have it pulled already


class OllamaError(RuntimeError):
    pass


def call_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    api_url: str = OLLAMA_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_predict": max_tokens},
    }).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OllamaError(f"Ollama API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OllamaError(f"Ollama server unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Ollama server returned invalid JSON: {exc}") from exc


def _extract_text(response: dict[str, Any]) -> str:
    return response.get("message", {}).get("content", "") or ""


def _extract_usage(response: dict[str, Any]) -> dict[str, Any]:
    return {
        key: response[key]
        for key in ("prompt_eval_count", "eval_count", "total_duration")
        if key in response
    }


def make_ollama_agent(
    name: str,
    objective: str = "generate_text",
    model: str = DEFAULT_MODEL,
    capabilities: list[str] | None = None,
    api_url: str = OLLAMA_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user message to a local
    Ollama server. No API key — unlike the other Level 3 adapters, Ollama
    serves localhost by default; point `api_url` at a remote/authenticated
    proxy if that's your deployment."""
    agent = Agent(name=name, capabilities=capabilities or [objective])

    @agent.task(objective)
    def handle(task: Task) -> dict[str, Any] | ErrorPayload:
        prompt = task.input.get("prompt")
        if not prompt:
            return agent.fail(
                task, error_code="missing_prompt",
                message="task.input['prompt'] is required", retryable=False,
            )
        try:
            response = call_ollama(prompt, model=model, api_url=api_url)
        except OllamaError as exc:
            return agent.fail(task, error_code="ollama_api_error", message=str(exc), retryable=True)
        return {
            "text": _extract_text(response),
            "model": response.get("model", model),
            "usage": _extract_usage(response),
        }

    return agent
