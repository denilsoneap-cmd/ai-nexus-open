"""Shared HTTP plumbing for OpenAI-wire-compatible adapters. `openai.py`,
`deepseek.py`, `openrouter.py`, `qwen.py`, and `vllm.py` all speak the exact
same Chat Completions request/response shape (only base URL, default model,
API-key variable, and exception class differ) — this module holds the one
copy of that shared shape so a future fix (timeout handling, a new field,
error-message wording) lands in one place instead of being hand-applied
across five (soon to be more, per ROADMAP.md's remaining Level 3 vendors)
near-identical files.

Not an adapter itself — no `make_*_agent` here. Each adapter file still
defines its own `call_*` wrapper (with its own default model/URL/exception
class) and its own `make_*_agent` factory, so `NexusCore` still only ever
sees a plain `Agent` (ARCHITECTURE.md principle 1) and every adapter file
stays independently readable without importing five others to understand one.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def post_chat_completion(
    *,
    prompt: str,
    model: str,
    api_url: str,
    timeout: float,
    max_tokens: int,
    api_key: str | None,
    vendor: str,
    error_cls: type[Exception],
) -> dict[str, Any]:
    """POSTs a single-user-message Chat Completions request. `api_key` is
    only attached as an `Authorization: Bearer` header when truthy — vLLM
    is commonly run unauthenticated, so omitting the header entirely (not
    sending an empty one) matters for that adapter."""
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
        raise error_cls(f"{vendor} API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise error_cls(f"{vendor} API unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise error_cls(f"{vendor} API returned invalid JSON: {exc}") from exc


def extract_message_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""
