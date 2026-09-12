"""Level 3 (Model Universe) — wraps DeepSeek's OpenAI-compatible Chat
Completions API as a Nexus Agent, using stdlib `urllib` (no `openai` SDK
dependency). Same shape as `nexus.adapters.openai`/`nexus.adapters.qwen` on
purpose (ARCHITECTURE.md principle 1): DeepSeek's API speaks the exact same
request/response schema as OpenAI, so this adapter only supplies DeepSeek's
own base URL, default model, error class, and API key variable — the shared
HTTP/error-handling/text-extraction plumbing lives in
`nexus.adapters._openai_compatible`.

Like `nexus.adapters.openai`, this calls a real, paid API and is never
exercised for real in this project's own tests; tests point `api_url` at a
local fake HTTP server.
"""

from __future__ import annotations

import os
from typing import Any

from ..agent import Agent
from ..protocol import ErrorPayload, Task
from ._openai_compatible import extract_message_text, post_chat_completion

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"  # cheapest current model — a sane default for a generic adapter


class DeepSeekError(RuntimeError):
    pass


def call_deepseek(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    api_url: str = DEEPSEEK_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    return post_chat_completion(
        prompt=prompt, model=model, api_url=api_url, timeout=timeout,
        max_tokens=max_tokens, api_key=api_key, vendor="DeepSeek", error_cls=DeepSeekError,
    )


def make_deepseek_agent(
    name: str,
    objective: str = "generate_text",
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    capabilities: list[str] | None = None,
    api_url: str = DEEPSEEK_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user message. `api_key`
    falls back to `DEEPSEEK_API_KEY`, resolved once at agent-construction
    time — identical contract to `nexus.adapters.openai.make_openai_agent`."""
    resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    agent = Agent(name=name, capabilities=capabilities or [objective])

    @agent.task(objective)
    def handle(task: Task) -> dict[str, Any] | ErrorPayload:
        if not resolved_key:
            return agent.fail(
                task, error_code="missing_api_key",
                message="DEEPSEEK_API_KEY is not set and no api_key was provided", retryable=False,
            )
        prompt = task.input.get("prompt")
        if not prompt:
            return agent.fail(
                task, error_code="missing_prompt",
                message="task.input['prompt'] is required", retryable=False,
            )
        try:
            response = call_deepseek(prompt, api_key=resolved_key, model=model, api_url=api_url)
        except DeepSeekError as exc:
            return agent.fail(task, error_code="deepseek_api_error", message=str(exc), retryable=True)
        return {
            "text": extract_message_text(response),
            "model": response.get("model", model),
            "usage": response.get("usage", {}),
        }

    return agent
