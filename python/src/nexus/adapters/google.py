"""Level 3 (Model Universe) — wraps the Google Gemini `generateContent` API
as a Nexus Agent, using stdlib `urllib` (no `google-generativeai` SDK
dependency). Same shape as `nexus.adapters.openai`/`nexus.adapters.anthropic`
on purpose (ARCHITECTURE.md principle 1): `task.input["prompt"]` in,
`{text, model, usage}` out, API key resolved from an argument or an
environment variable at agent-construction time.

Gemini's request/response shape differs from the OpenAI-style adapters
(`contents[].parts[].text` instead of `messages`, `candidates` instead of
`choices`, the key goes in the URL as a query parameter instead of an
`Authorization` header) — those are exactly the differences this adapter
layer exists to absorb so `NexusCore` never has to know about them.

Like `nexus.adapters.openai`, this calls a real, paid API and is never
exercised for real in this project's own tests; tests point `api_url` at a
local fake HTTP server.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task

GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.0-flash"  # cheapest current model — a sane default for a generic adapter


class GoogleError(RuntimeError):
    pass


def call_google(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    api_url: str = GOOGLE_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    url = api_url.format(model=model) + "?" + urllib.parse.urlencode({"key": api_key})
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GoogleError(f"Google API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GoogleError(f"Google API unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GoogleError(f"Google API returned invalid JSON: {exc}") from exc


def _extract_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def make_google_agent(
    name: str,
    objective: str = "generate_text",
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    capabilities: list[str] | None = None,
    api_url: str = GOOGLE_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user part. `api_key` falls
    back to `GOOGLE_API_KEY`, resolved once at agent-construction time —
    identical contract to `nexus.adapters.openai.make_openai_agent`."""
    resolved_key = api_key or os.environ.get("GOOGLE_API_KEY")
    agent = Agent(name=name, capabilities=capabilities or [objective])

    @agent.task(objective)
    def handle(task: Task) -> dict[str, Any] | ErrorPayload:
        if not resolved_key:
            return agent.fail(
                task, error_code="missing_api_key",
                message="GOOGLE_API_KEY is not set and no api_key was provided", retryable=False,
            )
        prompt = task.input.get("prompt")
        if not prompt:
            return agent.fail(
                task, error_code="missing_prompt",
                message="task.input['prompt'] is required", retryable=False,
            )
        try:
            response = call_google(prompt, api_key=resolved_key, model=model, api_url=api_url)
        except GoogleError as exc:
            return agent.fail(task, error_code="google_api_error", message=str(exc), retryable=True)
        return {
            "text": _extract_text(response),
            "model": response.get("modelVersion", model),
            "usage": response.get("usageMetadata", {}),
        }

    return agent
