"""Level 3 (Model Universe) — wraps the OpenAI Chat Completions API as a
Nexus Agent, using stdlib `urllib` (no `openai` SDK dependency). Same shape
as `nexus.adapters.anthropic` on purpose: `task.input["prompt"]` in,
`{text, model, usage}` out, API key resolved from an argument or an
environment variable at agent-construction time — the point of Level 3 is
that swapping one model provider for another is a config change, not a
different integration pattern (ARCHITECTURE.md principle 1).

Like `nexus.adapters.anthropic`, this calls a real, paid API and is never
exercised for real in this project's own tests; tests point `api_url` at a
local fake HTTP server.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"  # cheapest current model — a sane default for a generic adapter


class OpenAIError(RuntimeError):
    pass


def call_openai(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    api_url: str = OPENAI_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body = json.dumps({
        "model": model,
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpenAIError(f"OpenAI API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OpenAIError(f"OpenAI API unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAIError(f"OpenAI API returned invalid JSON: {exc}") from exc


def _extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


def make_openai_agent(
    name: str,
    objective: str = "generate_text",
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    capabilities: list[str] | None = None,
    api_url: str = OPENAI_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user message. `api_key`
    falls back to `OPENAI_API_KEY`, resolved once at agent-construction
    time — identical contract to `nexus.adapters.anthropic.make_anthropic_agent`."""
    resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
    agent = Agent(name=name, capabilities=capabilities or [objective])

    @agent.task(objective)
    def handle(task: Task) -> dict[str, Any] | ErrorPayload:
        if not resolved_key:
            return agent.fail(
                task, error_code="missing_api_key",
                message="OPENAI_API_KEY is not set and no api_key was provided", retryable=False,
            )
        prompt = task.input.get("prompt")
        if not prompt:
            return agent.fail(
                task, error_code="missing_prompt",
                message="task.input['prompt'] is required", retryable=False,
            )
        try:
            response = call_openai(prompt, api_key=resolved_key, model=model, api_url=api_url)
        except OpenAIError as exc:
            return agent.fail(task, error_code="openai_api_error", message=str(exc), retryable=True)
        return {
            "text": _extract_text(response),
            "model": response.get("model", model),
            "usage": response.get("usage", {}),
        }

    return agent
