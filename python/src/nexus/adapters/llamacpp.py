"""Level 3 (Model Universe) — wraps `llama.cpp`'s own server
(`llama-server`) OpenAI-compatible `/v1/chat/completions` endpoint as a
Nexus Agent, using stdlib `urllib` (no SDK dependency). Same wire shape as
`nexus.adapters.openai` — the shared HTTP/error-handling/text-extraction
plumbing lives in `nexus.adapters._openai_compatible` — and the same
self-hosted-server story as `nexus.adapters.vllm`: no sane `DEFAULT_MODEL`
(the server exposes whatever `.gguf` was loaded at startup, and largely
ignores the `model` field anyway), and an optional rather than required API
key (`llama-server` runs unauthenticated unless started with `--api-key`).
`model` is required and keyword-only for the same reason as `vllm.py`: a
required positional could silently bind a caller's `objective` into it.

This project's own tests point `api_url` at a local fake HTTP server, same
as every other adapter — they do not require a real `llama-server` running.
"""

from __future__ import annotations

import os
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task
from ._openai_compatible import extract_message_text, post_chat_completion

LLAMACPP_API_URL = "http://localhost:8080/v1/chat/completions"


class LlamaCppError(RuntimeError):
    pass


def call_llamacpp(
    prompt: str,
    *,
    model: str,
    api_key: str | None = None,
    max_tokens: int = 1024,
    api_url: str = LLAMACPP_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    return post_chat_completion(
        prompt=prompt, model=model, api_url=api_url, timeout=timeout,
        max_tokens=max_tokens, api_key=api_key, vendor="llama.cpp", error_cls=LlamaCppError,
    )


def make_llamacpp_agent(
    name: str,
    *,
    model: str,
    objective: str = "generate_text",
    api_key: str | None = None,
    capabilities: list[str] | None = None,
    api_url: str = LLAMACPP_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user message to a local
    `llama-server`. `model` is required (the server has no universal
    default — it serves whatever `.gguf` was loaded at startup, same
    reasoning as `nexus.adapters.vllm.make_vllm_agent`). `api_key` falls
    back to `LLAMACPP_API_KEY`, but unlike the cloud adapters, no key at all
    is a valid configuration (`llama-server` commonly runs unauthenticated)."""
    resolved_key = api_key or os.environ.get("LLAMACPP_API_KEY")
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
            response = call_llamacpp(prompt, model=model, api_key=resolved_key, api_url=api_url)
        except LlamaCppError as exc:
            return agent.fail(task, error_code="llamacpp_api_error", message=str(exc), retryable=True)
        return {
            "text": extract_message_text(response),
            "model": response.get("model", model),
            "usage": response.get("usage", {}),
        }

    return agent
