"""Level 3 (Model Universe) — wraps the Anthropic Messages API as a Nexus
Agent, using stdlib `urllib` (no `anthropic` SDK dependency), consistent
with `nexus.adapters.n8n` and `nexus.adapters.registry`.

This is the first adapter in this project that calls a real, paid LLM API —
unlike n8n/Ruflo/Superpowers, it needs a real API key and costs real money
per call. Like `nexus.adapters.ruflo`'s `cli_runner`, it is never exercised
for real in this project's own test suite for exactly that reason; tests
point `api_url` at a local fake HTTP server instead.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # cheapest current model — a sane default for a generic adapter


class AnthropicError(RuntimeError):
    pass


def call_anthropic(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    api_url: str = ANTHROPIC_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AnthropicError(f"Anthropic API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AnthropicError(f"Anthropic API unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AnthropicError(f"Anthropic API returned invalid JSON: {exc}") from exc


def _extract_text(response: dict[str, Any]) -> str:
    parts = response.get("content", [])
    return "".join(part.get("text", "") for part in parts if part.get("type") == "text")


def make_anthropic_agent(
    name: str,
    objective: str = "generate_text",
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    capabilities: list[str] | None = None,
    api_url: str = ANTHROPIC_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user message. `api_key`
    falls back to the `ANTHROPIC_API_KEY` environment variable, resolved
    once at agent-construction time (not per-call) — matching how a real
    deployment would configure a long-lived agent."""
    resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    agent = Agent(name=name, capabilities=capabilities or [objective])

    @agent.task(objective)
    def handle(task: Task) -> dict[str, Any] | ErrorPayload:
        if not resolved_key:
            return agent.fail(
                task, error_code="missing_api_key",
                message="ANTHROPIC_API_KEY is not set and no api_key was provided", retryable=False,
            )
        prompt = task.input.get("prompt")
        if not prompt:
            return agent.fail(
                task, error_code="missing_prompt",
                message="task.input['prompt'] is required", retryable=False,
            )
        try:
            response = call_anthropic(prompt, api_key=resolved_key, model=model, api_url=api_url)
        except AnthropicError as exc:
            return agent.fail(task, error_code="anthropic_api_error", message=str(exc), retryable=True)
        return {
            "text": _extract_text(response),
            "model": response.get("model", model),
            "usage": response.get("usage", {}),
        }

    return agent
