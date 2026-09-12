"""Level 3 (Model Universe) — wraps a self-hosted vLLM server's
OpenAI-compatible `/v1/chat/completions` endpoint as a Nexus Agent, using
stdlib `urllib` (no `openai`/`vllm` SDK dependency). Same wire shape as
`nexus.adapters.openai` (vLLM's whole point is OpenAI API compatibility),
but a different auth story: like `nexus.adapters.ollama`, this is meant for
a self-hosted server, so an API key is optional rather than required —
vLLM is commonly run with no auth at all on a private network, and only
sometimes fronted by a `--api-key`.

Unlike every other cloud-model adapter in this package, there is no sane
`DEFAULT_MODEL`: vLLM serves whatever model the operator loaded at startup,
so `model` is a required argument here, not a default with a fallback.

This project's own tests point `api_url` at a local fake HTTP server, same
as every other adapter — they do not require a real vLLM server running.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task

VLLM_API_URL = "http://localhost:8000/v1/chat/completions"


class VLLMError(RuntimeError):
    pass


def call_vllm(
    prompt: str,
    model: str,
    api_key: str | None = None,
    max_tokens: int = 1024,
    api_url: str = VLLM_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(api_url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VLLMError(f"vLLM API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise VLLMError(f"vLLM server unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VLLMError(f"vLLM server returned invalid JSON: {exc}") from exc


def _extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


def make_vllm_agent(
    name: str,
    model: str,
    objective: str = "generate_text",
    api_key: str | None = None,
    capabilities: list[str] | None = None,
    api_url: str = VLLM_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user message to a
    self-hosted vLLM server. `model` is required (vLLM has no universal
    default — it serves whatever was loaded at startup). `api_key` falls
    back to `VLLM_API_KEY`, but unlike the cloud adapters, no key at all is
    a valid configuration (vLLM commonly runs unauthenticated)."""
    resolved_key = api_key or os.environ.get("VLLM_API_KEY")
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
            response = call_vllm(prompt, model=model, api_key=resolved_key, api_url=api_url)
        except VLLMError as exc:
            return agent.fail(task, error_code="vllm_api_error", message=str(exc), retryable=True)
        return {
            "text": _extract_text(response),
            "model": response.get("model", model),
            "usage": response.get("usage", {}),
        }

    return agent
