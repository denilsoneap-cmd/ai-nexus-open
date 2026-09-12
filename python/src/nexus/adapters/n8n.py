"""Level 11 (Workflow) — sends a Nexus task to an n8n webhook and turns the
JSON response into a Result or ErrorPayload.

n8n is treated purely as an execution backend behind a webhook, per
ARCHITECTURE.md principle 1: nothing here is n8n-specific beyond "POST JSON,
read JSON back," so the same shape works for any HTTP workflow engine.
`make_n8n_agent` wraps this into an ordinary `Agent` so `NexusCore.route()`
needs no n8n-specific code path.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..agent import Agent
from ..protocol import ErrorPayload, Result, Task


class N8nAdapter:
    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send_task(self, task: Task) -> Result | ErrorPayload:
        body = json.dumps(task.to_payload()).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            return ErrorPayload(
                task_id=task.id,
                error_code="n8n_unreachable",
                message=str(exc),
                retryable=True,
            )
        except json.JSONDecodeError as exc:
            return ErrorPayload(
                task_id=task.id,
                error_code="n8n_invalid_response",
                message=f"webhook did not return valid JSON: {exc}",
                retryable=False,
            )

        if "error_code" in data:
            data.setdefault("task_id", task.id)
            return ErrorPayload.from_payload(data)
        data.setdefault("task_id", task.id)
        return Result.from_payload(data)


def make_n8n_agent(
    name: str,
    objective_webhooks: dict[str, str],
    capabilities: list[str] | None = None,
    timeout: float = 10.0,
) -> Agent:
    """Build an Agent whose task handlers each forward to an n8n webhook.
    `objective_webhooks` maps a Nexus objective to the webhook URL that
    handles it, e.g. `{"send_invoice_email": "https://n8n.local/webhook/..."}`.
    """
    agent = Agent(name=name, capabilities=capabilities or list(objective_webhooks))

    for objective, webhook_url in objective_webhooks.items():
        adapter = N8nAdapter(webhook_url, timeout=timeout)

        def handler(task: Task, _adapter: N8nAdapter = adapter) -> Result | ErrorPayload:
            return _adapter.send_task(task)

        agent.task(objective)(handler)

    return agent
