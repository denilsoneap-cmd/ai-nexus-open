# RFC-0005: Debate + Arbitration

- **Status**: Draft
- **Author(s)**: Denilson (Founder / Initial Maintainer)
- **Created**: 2026-09-12
- **Supersedes / Superseded by**: none (implements ROADMAP.md Level 7)

## Summary

This RFC defines how Nexus reconciles disagreement when the same task is
sent to more than one agent: not by voting, but by comparing how strong each
candidate's own attached evidence is (RFC-0001 §5), using the same weighting
formula RFC-0004 already established for historical trust — applied here
per-decision instead of per-agent-history. `NexusCore.debate()` fans a task
out to every capable agent and returns a `Verdict` naming a winner and
showing its reasoning, never a silent majority pick.

## Motivation

ARCHITECTURE.md principle 3 has said since Genesis: "the system does not
average or vote by default... The Arbitration Engine looks for the argument
with the strongest evidence, not the most votes." Until now nothing
implemented that — `NexusCore.route()` only ever asks one agent. This RFC is
the first thing in the project that actually reconciles more than one
agent's answer to the same question, which is also the point where RFC-0004
explicitly said its own trust score stops being enough: an agent's *history*
should not decide the answer to *this* question when the evidence in front
of us already does.

## Design

### 1. Candidates and Verdicts

```python
@dataclass
class Candidate:
    agent_id: str
    result: Result          # RFC-0001 §4.1, may carry its own Evidence

@dataclass
class Verdict:
    task_id: str
    winner_agent_id: str
    winning_result: Result
    agreement: bool         # did every candidate produce the same output?
    reasoning: str          # human-readable explanation, always populated
    candidates: list[dict]  # per-candidate breakdown, for every candidate
```

A `Verdict` is not just a winner — `candidates` and `reasoning` exist so a
disagreement can be inspected after the fact (ARCHITECTURE.md principle 7).

### 2. Agreement is checked first, literally

If every candidate's `Result.output` is exactly equal, `agreement=True` and
the first candidate's result is the (arbitrary, since they all agree)
answer — no evidence comparison needed. This RFC does **not** attempt
semantic equivalence between differently-shaped outputs that mean the same
thing; only byte-for-byte equality counts as agreement. Anything else falls
through to §3. This is a deliberate limitation, not an oversight — see
Alternatives Considered.

### 3. Disagreement: evidence strength, then trust, never votes

When outputs differ, each candidate is scored by
`nexus.trust.evidence_strength(candidate.result.evidence)` — the exact same
formula RFC-0004 uses, applied to the evidence attached to *this* result
only, not the agent's full history. The highest-evidence-strength candidate
wins. On an exact tie, historical trust (RFC-0004's `TrustEvaluator`, given
a historical evidence pool) breaks it. On a further tie — including the
common case of no evidence anywhere and no historical pool supplied — the
first candidate in input order wins, deterministically, the same "stable
first-match" guarantee RFC-0004 made for routing.

Note what this deliberately does not do: count how many candidates landed
on the same answer. Three agents confidently repeating an unsupported claim
does not outweigh one agent with `extracted_verbatim` evidence at high
confidence — repeating principle 3 exactly.

### 4. `NexusCore.debate()`

```python
def debate(self, objective: str, input: dict | None = None,
           agent_ids: list[str] | None = None, task_id: str | None = None) -> Verdict:
    ...
```

Sends the same `Task` to every agent capable of `objective` (or a subset
named by `agent_ids`), calling `agent.handle(task)` on each in turn and
collecting the results, then arbitrating. Requires `NexusCore(arbiter=...)`
to be configured — unlike `route()`, there is no sane default behavior for
"no arbiter provided," so this raises rather than silently degrading.

An agent that raises `CapabilityUnavailable` or `TaskFailed` while debating
is dropped from consideration rather than failing the whole debate — a
partial debate among agents that actually answered is more useful than none
at all. If **no** candidate produces a usable result, `debate()` raises.

### 5. Known limitations (scoped out of this RFC)

- `debate()` does not record anything into `NexusCore.trace`, the audit log,
  or the graph store the way `route()` does. Wiring that in was left out to
  keep this RFC's diff reviewable; it is a real gap, not a design decision,
  tracked in ROADMAP.md.
- Calling every capable agent synchronously, one after another, is not
  parallel and not cheap — fine at this project's scale, a real problem once
  "debate" means five expensive LLM calls. Execution model (parallel, with
  timeouts) is Level 8/9 territory, not this RFC's.
- There is no limit on how many agents get debated — sending a task to 50
  registered agents because they all declared the same capability is
  possible today and probably not what anyone wants. Not addressed here.

## Alignment with architecture principles

1. **Vendor neutrality** — arbitration only ever looks at `Result`/`Evidence`
   shapes, never at which model produced them.
2. **Protocol over implementation** — `Candidate`/`Verdict` are plain
   dataclasses over RFC-0001 objects; no new wire format.
3. **No forced consensus** — this RFC *is* that principle, implemented.
4. **Evidence before trust** — reuses RFC-0004's own ordering: evidence
   strength before historical trust, historical trust before an arbitrary
   tiebreak, self-reported anything never in the loop.
5. **Simulate before executing** — unaffected; `debate()` still just
   compares already-produced results, it does not decide whether to act on
   the winner.
6. **Free/local-first when sufficient** — unaffected.
7. **Everything is observable** — `Verdict.candidates` shows every
   candidate's score, not just the winner's.
8. **Anyone can extend it without permission** — `ArbitrationEngine` takes
   an injected `TrustEvaluator`, so a deployment can recalibrate weighting
   without forking this module, same pattern as RFC-0004.

## Alternatives considered

- **Majority vote**: rejected outright — this is precisely what principle 3
  forbids, and what motivated writing this RFC in the first place.
- **Semantic-similarity clustering of outputs before comparing** (e.g.
  embedding-based "these two answers probably mean the same thing"):
  attractive but adds a real dependency (an embedding model) and a real
  failure mode (false-positive clustering hiding a genuine disagreement) to
  a layer whose entire job is surfacing disagreement honestly. Deferred —
  byte-equality is a conservative default that never hides a real conflict,
  only occasionally fails to notice two independently-worded agreements.
- **Weighting by number of candidates that agree, as a secondary signal
  after evidence strength**: considered and rejected — reintroducing vote
  counting anywhere in the ranking, even as a tiebreak, undermines the
  principle this RFC exists to implement. The tiebreak is trust
  (something-earned), not count (nothing-earned).

## Backward compatibility

Purely additive. `NexusCore(arbiter=None)` (the default) means `debate()`
is simply unavailable (it raises); `route()`'s behavior is completely
unaffected by this RFC.

## Open questions

- Should `debate()` accept a minimum quorum (e.g. "need at least 3
  responses") before arbitrating? Not implemented — revisit once a real
  caller needs it.
- Wiring `debate()` into `trace`/`audit`/`graph` (§5) — tracked, not
  designed yet; probably wants its own small RFC once Level 9 observability
  is revisited, rather than bolting it on here.
- Concurrency/timeout model for fan-out (§5) is entirely unaddressed and
  will need real design once `debate()` is used with agents slow enough for
  it to matter (e.g. real Ruflo-spawned agents, `nexus.adapters.ruflo`).
