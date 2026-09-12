"""Level 3 (Model Universe) — wraps a self-hosted vLLM server's
OpenAI-compatible `/v1/chat/completions` endpoint as a Nexus Agent, using
stdlib `urllib` (no `openai`/`vllm` SDK dependency). Same wire shape as
`nexus.adapters.openai` (vLLM's whole point is OpenAI API compatibility) —
the shared HTTP/error-handling/text-extraction plumbing lives in
`nexus.adapters._openai_compatible` — but a different auth story: like
`nexus.adapters.ollama`, this is meant for a self-hosted server, so an API
key is optional rather than required — vLLM is commonly run with no auth at
all on a private network, and only sometimes fronted by a `--api-key`.

Unlike every other cloud-model adapter in this package, there is no sane
`DEFAULT_MODEL`: vLLM serves whatever model the operator loaded at startup,
so `model` is required here, not a default with a fallback. It's
keyword-only (`*, model: str`) rather than a plain required positional, so
`call_vllm`/`make_vllm_agent` can't have a caller's `objective` or `api_key`
silently bind into the `model` slot by position — every other adapter in
this package takes `model` as a keyword-with-default for the same reason.

This project's own tests point `api_url` at a local fake HTTP server, same
as every other adapter — they do not require a real vLLM server running.
"""

from __future__ import annotations

import os
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task
from ._openai_compatible import extract_message_text, post_chat_completion

VLLM_API_URL = "http://localhost:8000/v1/chat/completions"


class VLLMError(RuntimeError):
    pass


def call_vllm(
    prompt: str,
    *,
    model: str,
    api_key: str | None = None,
    max_tokens: int = 1024,
    api_url: str = VLLM_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    return post_chat_completion(
        prompt=prompt, model=model, api_url=api_url, timeout=timeout,
        max_tokens=max_tokens, api_key=api_key, vendor="vLLM", error_cls=VLLMError,
    )


def make_vllm_agent(
    name: str,
    *,
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
            "text": extract_message_text(response),
            "model": response.get("model", model),
            "usage": response.get("usage", {}),
        }

    return agent
