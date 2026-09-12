"""Level 3 (Model Universe) — wraps ByteDance's Doubao models via the
Volcengine Ark OpenAI-compatible Chat Completions endpoint as a Nexus
Agent, using stdlib `urllib` (no `volcengine`/`openai` SDK dependency). Same
wire shape as `nexus.adapters.openai` — the shared HTTP/error-handling/
text-extraction plumbing lives in `nexus.adapters._openai_compatible` — but,
like `nexus.adapters.vllm`, there is no sane `DEFAULT_MODEL`: Ark identifies
a deployed model by an operator-provisioned endpoint ID (`ep-...`), not a
shared model name, so `model` is required and keyword-only here too (same
reasoning as `vllm.py`: a required positional would risk silently binding a
caller's `objective` into the `model` slot).

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

DOUBAO_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


class DoubaoError(RuntimeError):
    pass


def call_doubao(
    prompt: str,
    api_key: str,
    *,
    model: str,
    max_tokens: int = 1024,
    api_url: str = DOUBAO_API_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    return post_chat_completion(
        prompt=prompt, model=model, api_url=api_url, timeout=timeout,
        max_tokens=max_tokens, api_key=api_key, vendor="Doubao", error_cls=DoubaoError,
    )


def make_doubao_agent(
    name: str,
    *,
    model: str,
    objective: str = "generate_text",
    api_key: str | None = None,
    capabilities: list[str] | None = None,
    api_url: str = DOUBAO_API_URL,
) -> Agent:
    """`task.input["prompt"]` is sent as a single user message. `model` is
    required — Ark identifies a deployed model by an operator-provisioned
    endpoint ID (`ep-...`), so there is no universal default (same reasoning
    as `nexus.adapters.vllm.make_vllm_agent`). `api_key` falls back to
    `DOUBAO_API_KEY`, resolved once at agent-construction time."""
    resolved_key = api_key or os.environ.get("DOUBAO_API_KEY")
    agent = Agent(name=name, capabilities=capabilities or [objective])

    @agent.task(objective)
    def handle(task: Task) -> dict[str, Any] | ErrorPayload:
        if not resolved_key:
            return agent.fail(
                task, error_code="missing_api_key",
                message="DOUBAO_API_KEY is not set and no api_key was provided", retryable=False,
            )
        prompt = task.input.get("prompt")
        if not prompt:
            return agent.fail(
                task, error_code="missing_prompt",
                message="task.input['prompt'] is required", retryable=False,
            )
        try:
            response = call_doubao(prompt, api_key=resolved_key, model=model, api_url=api_url)
        except DoubaoError as exc:
            return agent.fail(task, error_code="doubao_api_error", message=str(exc), retryable=True)
        return {
            "text": extract_message_text(response),
            "model": response.get("model", model),
            "usage": response.get("usage", {}),
        }

    return agent
