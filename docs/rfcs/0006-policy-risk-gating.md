# RFC-0006: Policy — Risk-Based Approval Gating

- **Status**: Draft
- **Author(s)**: Denilson (Founder / Initial Maintainer)
- **Created**: 2026-09-12
- **Supersedes / Superseded by**: none (implements ROADMAP.md Level 8)

## Summary

This RFC makes `task.risk` (RFC-0001 §4, carried today as A2A metadata per
RFC-0003 §3) actually mean something: a `PolicyEngine` evaluates it against
a configurable risk-to-action map before `NexusCore.route()` will dispatch a
task to any agent, and can require an explicit approval callback for
high-risk work. It **fails closed** — a task whose risk requires approval,
with no approver configured, is blocked, not allowed through.

## Motivation

ARCHITECTURE.md principle 5 has said since Genesis: "Any action with
real-world side effects (delete, spend, send, deploy) follows: `plan ->
simulate -> assess risk -> approve -> execute -> audit`. Critical-risk
actions require human approval by default." RFC-0001 §4 defined `task.risk`
specifically so this would eventually be enforceable, and said outright:
"the Policy layer is the authority, not this field." Until now, nothing was
that authority — `task.risk` traveled all the way from RFC-0001 through
RFC-0003's A2A metadata mapping into `Task.risk` and was never read by
anything. A task declaring `risk: "critical"` and a task declaring nothing
were treated identically by `NexusCore.route()`.

## Design

### 1. Scope: risk gating, not the whole pipeline

Principle 5's full pipeline is `plan -> simulate -> assess risk -> approve
-> execute -> audit`. This RFC implements **assess risk -> approve ->
execute -> audit**. It does *not* implement `plan` or `simulate` — those
need an agent to expose a dry-run capability this project has no mechanism
for yet (see Open Questions). It also does not enforce `task.constraints`
(RFC-0001 §4's `"no_external_network"`, `"max_cost_usd:0.50"` style
declarations) — checking a constraint against what an agent/adapter
actually does would need a capability-tagging mechanism for adapters that
does not exist yet either. Both are real, acknowledged gaps, not
oversights.

### 2. Risk-to-action policy

```python
PolicyAction = Literal["allow", "block", "require_approval"]

DEFAULT_RISK_POLICY: dict[str | None, PolicyAction] = {
    None: "allow", "low": "allow", "medium": "allow",
    "high": "require_approval", "critical": "require_approval",
}
```

A risk value absent from the configured map resolves to `require_approval`,
not `allow` — an unmapped risk level is not evidence of safety. In practice
this guards a *custom* `risk_policy` that forgot to map one of RFC-0001
§4's four valid values (`Task.risk` is a closed set at the protocol layer;
an agent cannot invent a novel risk string), not an attacker-invented risk
level — but the same "missing means approval, not allow" rule applies
regardless of why an entry is missing. The map itself is a constructor
argument (`PolicyEngine(risk_policy=...)`), not hardcoded, per
ARCHITECTURE.md principle 8: a deployment can recalibrate what "high" means
without forking this module.

### 3. Approval fails closed

```python
def evaluate(self, task: Task) -> PolicyDecision:
    action = self.risk_policy.get(task.risk, "require_approval")
    if action == "allow":
        return PolicyDecision("allow", ...)
    if action == "require_approval":
        if self.approver is None:
            return PolicyDecision("block", "requires approval, none configured", ...)
        return PolicyDecision("allow" if self.approver(task, ...) else "block", ...)
    return PolicyDecision("block", ...)
```

`approver` is an injected `Callable[[Task, PolicyDecision], bool]` — the
same "injectable callback" pattern already used for
`nexus.adapters.n8n`/`superpowers`/`ruflo`. This project has no
human-approval UI, so the honest design is to let the integrator supply
one (a CLI prompt, a Slack approval flow, a hardcoded rule, a test double),
not to invent a fake one. **No approver configured means no approval is
possible, which means blocked** — "human approval by default" (principle 5)
means the absence of an approval mechanism is equivalent to approval
withheld, not equivalent to approval granted.

### 4. Wired into `NexusCore.route()`

Placed immediately after the task envelope is recorded (so a blocked task
still shows up in the trace — principle 7) and before agent lookup (so
policy is assessed before even checking whether a capable agent exists,
matching the pipeline's own ordering):

```python
task_envelope = envelope(...)
self._record(task_envelope)

if self.policy is not None:
    decision = self.policy.evaluate(task)
    if decision.action != "allow":
        error_envelope = envelope(message_type="error", ...,
                                   payload=ErrorPayload(task.id, "policy_blocked", decision.reason).to_payload(),
                                   correlation_id=task_envelope["message_id"])
        self._record(error_envelope)
        return error_envelope

candidates = self.find_by_objective(objective)
...
```

`NexusCore(policy=None)` (the default) reproduces every existing test
unchanged — this RFC changes nothing for a caller who does not opt in.

### 5. Audit visibility

A blocked task is fully visible in `self.trace`/`AuditLog` (if configured)
as an ordinary `error` envelope with `error_code: "policy_blocked"` — no new
message type or audit event kind was needed. An **allowed** task (whether
because its risk was fine, or because an approver said yes) is not
separately marked as "policy-reviewed" anywhere; it looks identical to a
task that never had a risk declared at all. That asymmetry is a real gap
(see Open Questions), not a design goal.

## Alignment with architecture principles

1. **Vendor neutrality** — the policy engine reads only `Task.risk`, a
   protocol field, never anything vendor-specific.
2. **Protocol over implementation** — `task.risk`'s meaning was already
   specified in RFC-0001 §4 ("a hint... the Policy layer is the authority");
   this RFC is that authority, not a protocol change.
3. **No forced consensus** — unaffected.
4. **Evidence before trust** — unaffected; orthogonal concern.
5. **Simulate before executing** — this RFC *is* the assess/approve/
   execute/audit half of that principle, explicitly not the plan/simulate
   half (§1).
6. **Free/local-first when sufficient** — unaffected.
7. **Everything is observable** — a blocked task's reason is a plain string
   in an ordinary error envelope, inspectable the same way any other error
   is (§5's asymmetry aside).
8. **Anyone can extend it without permission** — `risk_policy` and
   `approver` are both constructor arguments, not hardcoded branches.

## Alternatives considered

- **Enforcing `task.constraints` in this same RFC**: rejected for scope —
  constraints like `"no_external_network"` are only meaningful if something
  knows which agents/adapters touch the network, which nothing in this
  project tracks yet. Bundling it in here would mean shipping either a fake
  enforcement (checking nothing real) or a half-built capability-tagging
  system as a side effect of a policy RFC. Left as an explicit gap for a
  future RFC once adapters declare what they touch.
- **An async/awaitable approver** (for a Slack-approval-style flow that
  waits on a human): rejected for this RFC — `NexusCore.route()` is
  synchronous end to end today; adding async here would mean either forking
  the whole call chain or faking synchronicity over an inherently
  asynchronous flow. A synchronous `approver` can still front a real async
  system (e.g., block on a future, poll a ticket) at the integration's own
  risk; this RFC's contract doesn't need to know.
- **Defaulting unrecognized risk values to `"allow"`**: rejected — silently
  trusting a value nobody defined the meaning of is exactly the kind of
  unearned trust ARCHITECTURE.md principle 4 (in its Evidence-before-trust
  form) already rejects for a different concept; the same reasoning applies
  here.

## Backward compatibility

Additive only. `NexusCore(policy=None)` is the default and reproduces all
existing behavior; no change to `route()`'s signature for existing callers.

## Open questions

- `task.constraints` enforcement (§1, Alternatives) — needs adapters to
  declare what they touch (network, cost, filesystem) before it can mean
  anything. Not designed here.
- Approved tasks are not distinguishable from never-risky ones in the audit
  trail (§5) — a future revision could add a dedicated `policy_decision`
  audit event for every evaluation, not only blocks, once there is a real
  caller who needs that distinction.
- `plan`/`simulate` (§1) — needs agents to expose a dry-run mode. Not
  designed here; likely needs its own RFC once a real use case exists
  (e.g., simulating a `nexus.adapters.ruflo` spawn before actually calling
  a paid LLM provider).
- Should policy apply to `NexusCore.debate()` as well as `route()`? Not
  wired in this RFC — `debate()` already has its own documented gaps
  (RFC-0005 §5); adding policy there is a follow-up, not bundled here to
  keep this RFC's diff reviewable.
