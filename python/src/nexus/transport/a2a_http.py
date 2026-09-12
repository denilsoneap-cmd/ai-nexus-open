"""Level 1's previously-open gap: a real *networked* A2A transport.
Wraps `a2a-sdk` (github.com/a2aproject/a2a-python, the official Python SDK,
Apache-2.0) rather than hand-rolling JSON-RPC — `nexus.a2a` already maps
Nexus's own objects to A2A's wire *shapes* for round-tripping in-process;
this module is what actually moves them over a real HTTP connection, so an
external A2A-compliant agent or orchestrator can reach a `NexusCore`, not
just another in-process Python caller. This is also what Level 4's
"discovery is not wired into dispatch" gap (RFC-0007 §5) was waiting on: a
registry card can now name a real `url`, and `call_remote_agent()` is what
actually calls it.

`a2a-sdk` v1.1.2 (the version this was built and tested against) is
protobuf-first internally (`a2a.types.*` are `a2a_pb2` protobuf messages,
not the plain camelCase JSON dicts RFC-0003's own tables describe — the
A2A spec itself has moved on since that RFC was written). So this module
does not reuse `nexus.a2a`'s dict-producing functions for the actual wire
encoding; it builds `a2a.types` objects directly via the SDK's own
`a2a.helpers`, using the same semantic convention RFC-0003 already
established (objective in `message.metadata["nexus.objective"]`, task
input as one data part) so the two stay conceptually aligned even though
the concrete types differ.

Optional dependency: `pip install "nexus-sdk[a2a]"` (pulls in `a2a-sdk`
and its server extras — Starlette/uvicorn/httpx/grpc). Nothing in
`nexus.core` imports this module — same vendor-neutrality principle
(ARCHITECTURE.md principle 1) as every other adapter/transport here.

Nexus's own dispatch (`NexusCore.route()`) is synchronous and single-shot
(one Task in, one Result/ErrorPayload out) — no streaming, no
input-required pauses — so the server side always follows a2a-sdk's
simplest "immediate response" workflow: create the task, run it to
completion, publish one artifact, mark it COMPLETED/FAILED.
"""

from __future__ import annotations

from typing import Any

from a2a.client import ClientConfig, create_client
from a2a.helpers import get_data_parts, new_data_part, new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Role,
    SendMessageRequest,
    TaskState,
)

from ..core import NexusCore
from ..protocol import ErrorPayload, Result

NEXUS_OBJECTIVE_METADATA_KEY = "nexus.objective"


class A2ATransportError(RuntimeError):
    pass


class NexusAgentExecutor(AgentExecutor):
    """Bridges a2a-sdk's `AgentExecutor` interface to `NexusCore.route()`.
    The incoming message's `metadata["nexus.objective"]` names the Nexus
    objective; its first data part (if any) is `task.input`. Missing
    objective, or `route()` itself failing, both end the task FAILED with
    the reason in the completion artifact — never a raised exception the
    a2a-sdk framework would otherwise turn into an opaque `TASK_STATE_ERROR`
    with no payload for the caller to inspect."""

    def __init__(self, core: NexusCore) -> None:
        self.core = core

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING, message=new_text_message("Routing to NexusCore..."),
        )

        # message.metadata is a google.protobuf.struct_pb2.Struct, not a
        # plain dict — it supports `in`/`[]` but not `.get()`.
        objective = (
            context.message.metadata[NEXUS_OBJECTIVE_METADATA_KEY]
            if NEXUS_OBJECTIVE_METADATA_KEY in context.message.metadata else None
        )
        if not objective:
            await updater.add_artifact(parts=[new_data_part(data={
                "error_code": "missing_objective",
                "message": f"message.metadata[{NEXUS_OBJECTIVE_METADATA_KEY!r}] is required",
            })])
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED, message=new_text_message("missing nexus.objective"),
            )
            return

        data_parts = get_data_parts(context.message.parts)
        task_input = data_parts[0] if data_parts else {}

        result_envelope = self.core.route(objective, input=task_input)
        await updater.add_artifact(parts=[new_data_part(data=result_envelope)])
        final_state = (
            TaskState.TASK_STATE_COMPLETED if result_envelope["message_type"] == "result"
            else TaskState.TASK_STATE_FAILED
        )
        await updater.update_status(state=final_state, message=new_text_message(result_envelope["message_type"]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("NexusCore.route() runs synchronously to completion; there is nothing to cancel.")


def build_agent_card(
    name: str,
    url: str,
    objectives: list[str],
    description: str = "",
    version: str = "0.1.0",
) -> AgentCard:
    """One `AgentSkill` per Nexus objective this server will route —
    matches how `nexus.a2a.to_agent_card` turns an `AgentIdentity`'s
    `capabilities` into A2A `skills`, but built from the SDK's own
    protobuf-backed type since that's what `DefaultRequestHandler`/
    `create_agent_card_routes` actually serve over HTTP."""
    skills = [
        AgentSkill(
            id=objective, name=objective, description=f"Nexus objective: {objective}",
            input_modes=["application/json"], output_modes=["application/json"], tags=["nexus"],
        )
        for objective in objectives
    ]
    return AgentCard(
        name=name,
        description=description or f"Nexus agent serving objectives: {', '.join(objectives)}",
        version=version,
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0"),
        ],
        skills=skills,
    )


def build_app(core: NexusCore, agent_card: AgentCard) -> Any:
    """A Starlette ASGI app — run it with any ASGI server
    (`uvicorn.run(app, ...)`). Not FastAPI: matches the official
    `a2a-samples` "helloworld" reference server exactly, and Starlette is
    already a transitive dependency of `a2a-sdk`'s server extra, so this
    adds nothing beyond what installing that extra already pulled in."""
    from starlette.applications import Starlette

    handler = DefaultRequestHandler(
        agent_executor=NexusAgentExecutor(core), task_store=InMemoryTaskStore(), agent_card=agent_card,
    )
    routes = []
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)


async def call_remote_agent(
    base_url: str,
    objective: str,
    task_input: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Calls a real, networked A2A agent (a `build_app`-served `NexusCore`,
    or any other A2A-compliant server) and returns the raw result payload
    (the `result_envelope` dict `NexusAgentExecutor` published as a data
    artifact — `{"message_type": "result"|"error", "payload": {...}, ...}`,
    the exact shape `NexusCore.route()` itself returns). Raises
    `A2ATransportError` on any network/protocol failure or if the server
    didn't reply with the expected artifact shape — the caller decides how
    to turn that into a local `ErrorPayload` (this module doesn't assume
    it's always wrapping a Nexus-to-Nexus call)."""
    import httpx

    from a2a.client import A2ACardResolver

    try:
        async with httpx.AsyncClient(timeout=timeout) as httpx_client:
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
            agent_card = await resolver.get_agent_card()

            client = await create_client(agent=agent_card, client_config=ClientConfig(streaming=False))
            try:
                message = new_text_message(
                    f"objective={objective}", role=Role.ROLE_USER,
                )
                message.metadata[NEXUS_OBJECTIVE_METADATA_KEY] = objective
                if task_input:
                    message.parts.append(new_data_part(data=task_input))
                request = SendMessageRequest(message=message)

                artifacts: list[dict[str, Any]] = []
                async for chunk in client.send_message(request):
                    task = getattr(chunk, "task", None) or (chunk if hasattr(chunk, "artifacts") else None)
                    if task is not None:
                        for artifact in task.artifacts:
                            artifacts.extend(get_data_parts(artifact.parts))
                if not artifacts:
                    raise A2ATransportError(f"{base_url} returned no data artifact for objective {objective!r}")
                return artifacts[-1]
            finally:
                await client.close()
    except A2ATransportError:
        raise
    except Exception as exc:  # noqa: BLE001 - any httpx/a2a-sdk failure becomes one transport error type
        raise A2ATransportError(f"call to {base_url} for objective {objective!r} failed: {exc}") from exc


async def dispatch_via_card(
    card: dict[str, Any],
    objective: str,
    task_input: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Result | ErrorPayload:
    """Level 4's discovery-to-dispatch gap (RFC-0007 §5), closed: finding a
    card via `nexus.discovery.FileRegistry.find_by_skill` used to mean
    nothing more could be done with it — this is what actually places the
    call, using `card["url"]` (set by `nexus.a2a.to_agent_card`/
    `nexus.discovery.publish_agent`'s optional `url` argument). Raises
    `A2ATransportError` if the card carries no `url` at all (discovery
    without a network transport is still a valid, supported state — see
    `nexus.a2a.to_agent_card`'s docstring — this function is simply not
    usable for a card in that state) or if the call itself fails; returns
    a `Result` or `ErrorPayload` — the same object shapes any other
    Nexus dispatch (`Agent.handle()`, `NexusCore.route()`) produces, so a
    caller doesn't need a special case for "this candidate happened to be
    remote."""
    url = card.get("url")
    if not url:
        raise A2ATransportError(f"AgentCard {card.get('id')!r} has no 'url' — it is not remotely dispatchable")

    result_envelope = await call_remote_agent(url, objective, task_input, timeout=timeout)
    message_type = result_envelope.get("message_type")
    payload = result_envelope.get("payload", {})
    if message_type == "result":
        return Result.from_payload(payload)
    if message_type == "error":
        return ErrorPayload.from_payload(payload)
    raise A2ATransportError(f"{url} returned an unrecognized message_type {message_type!r} for objective {objective!r}")
