# RFC-0004: Evidence-Derived Trust Scoring

- **Status**: Draft
- **Author(s)**: Denilson (Founder / Initial Maintainer)
- **Created**: 2026-09-12
- **Supersedes / Superseded by**: none (implements ROADMAP.md Level 6)

## Summary

This RFC defines how a Nexus agent's trust score is computed: from the
historical Evidence (RFC-0001 §5, carried today as an A2A extension per
RFC-0003 §4) that agent has actually produced, weighted by how strong each
piece of evidence's `transformation` type is, minus a penalty for any
lessons-learned recurrences (`nexus.adapters.lessons`) attributed to that
agent. It is explicitly **not** a general-purpose reputation system — it
answers one narrow question: *does this agent's own evidence-production
look careful?*

## Motivation

ARCHITECTURE.md principle 4 states: "Trust scores are derived from
historical evidence quality, not asserted." RFC-0002 deliberately left
`trust` out of the Agent Identity object for the same reason — an agent
cannot assert its own reliability. Until now, nothing computed a trust
score at all: `NexusCore.route()` picks the first capable agent
(ROADMAP.md Level 2), with a standing note that real selection was deferred
to this RFC.

This also has to be honest about its own limits. A proper trust signal
needs to know whether an agent's claims held up — was this evidence later
contradicted or corroborated by another agent? That signal does not exist
yet; it is Level 7's job (Debate + Arbitration) to produce it, once that RFC
is written. Shipping nothing until Level 7 exists would mean Level 2's
routing never improves past "first match" in the meantime. This RFC is
deliberately scoped to what evidence *already on file* can support today,
with an explicit, documented seam for Level 7's verdicts to plug into later
without changing this RFC's shape.

## Design

### 1. What is being scored

A trust score is computed **per agent_id**, from the set of `Evidence`
entries where `evidence.agent_id` equals that agent — i.e., evidence that
agent itself produced and attributed to itself (RFC-0001 §5's `agent_id`
field). It is not computed from evidence *about* the agent produced by
others; there is no such evidence yet (that too is a Level 7 concept —
"agent B verified agent A's claim").

### 2. Scoring formula

```python
TRANSFORMATION_WEIGHTS = {
    "extracted_verbatim": 1.0,
    "computed": 0.9,
    "summarized": 0.7,
    "inferred": 0.5,
}
```

For each evidence entry: `weighted_confidence = evidence.confidence *
TRANSFORMATION_WEIGHTS[evidence.transformation]`. An agent that only ever
reports 0.99 confidence on `inferred` claims should not outscore one
reporting 0.9 confidence on `extracted_verbatim` claims — self-reported
confidence alone is not enough, exactly the gap RFC-0001 §5 flagged
("Downstream trust scoring weighs these differently") without yet
specifying how. This RFC specifies it: multiply, don't just average
confidence alone.

```
raw_score = mean(weighted_confidence for each evidence entry)
penalty   = min(0.5, recurrences * 0.05)   # see §3
score     = clamp(0.0, 1.0, raw_score - penalty)
```

An agent with **zero evidence on file** gets `score = 0.0`, not a neutral
default — silence is not evidence of trustworthiness (consistent with
ARCHITECTURE.md principle 4: trust must be earned from evidence, never
assumed).

### 3. Recurrence penalty

`nexus.adapters.lessons.LessonStore` already tracks `recurrences` per
lesson — a count of how many times the same mistake happened again despite
a mechanism meant to prevent it. If lessons are tagged with the `agent_id`
responsible (not implemented yet in `lessons.py` — an open question, §
below), their total recurrence count feeds a flat penalty, capped at `0.5`
so a single bad pattern cannot alone zero out an otherwise well-evidenced
agent, while a genuinely repeat-offending agent's score degrades visibly.

### 4. Reference implementation

```python
class TrustEvaluator:
    def evaluate(self, agent_id: str, evidence: list[Evidence], recurrences: int = 0) -> TrustScore:
        ...
```

Deliberately **not** wired automatically into `NexusCore` as a required
dependency (per ARCHITECTURE.md principle 1 and the existing `GraphSink`/
`AuditSink` pattern): `NexusCore` gets an optional `trust: TrustEvaluator |
None` constructor argument. When set and more than one agent is capable of
an objective, `route()` computes each candidate's current score from
`self.trace`'s recorded evidence and picks the highest — replacing the
"first match" placeholder ROADMAP.md Level 2 has carried since Genesis.
When two agents tie (including the common zero-evidence/zero-evidence tie),
`route()` keeps the existing first-match order as the tiebreak, so behavior
without evidence on file is unchanged from before this RFC.

### 5. Transparency

Every `TrustScore` carries a `breakdown` dict (raw score, penalty, average
raw confidence) — per ARCHITECTURE.md principle 7 ("If a decision cannot be
explained after the fact, that is a defect"), a routing decision made on
trust must be able to show its work, not just emit a number.

## Alignment with architecture principles

1. **Vendor neutrality** — the formula is model-agnostic; it scores
   evidence-production behavior, not any specific backing model.
2. **Protocol over implementation** — the scoring inputs (Evidence
   entries) are the same RFC-0001 §5 objects any A2A-compliant agent
   already produces; this is not a new wire format.
3. **No forced consensus** — unaffected; this RFC scores individual agents,
   not how to reconcile disagreement (that remains Level 7's job).
4. **Evidence before trust** — this RFC *is* that principle, made concrete
   and formulaic instead of aspirational.
5. **Simulate before executing** — unaffected.
6. **Free/local-first when sufficient** — unaffected; a free/local agent
   with strong evidence scores exactly the same as a paid one.
7. **Everything is observable** — `TrustScore.breakdown` exists specifically
   for this.
8. **Anyone can extend it without permission** — `TRANSFORMATION_WEIGHTS`
   is an overridable constructor argument, not hardcoded, so a deployment
   can recalibrate without forking the evaluator.

## Alternatives considered

- **Behavior-based trust tiers** (à la `Ruflo/v3/@claude-flow/plugin-agent-federation`'s
  `TrustLevel` enum + `TrustEvaluator`, or Microsoft's Agent Governance
  Toolkit's 0–1000 score with five tiers): those score *identity/behavior*
  trust (has this node misbehaved on the network?) for an authorization
  decision. This RFC scores *evidence quality* for a routing decision. They
  answer different questions and are not mutually exclusive — a future RFC
  could add a behavior-trust layer for Level 8 (Policy) authorization
  decisions without touching this one.
- **A single global score updated incrementally (like an ELO rating)**:
  rejected for now — it requires the win/loss signal from Level 7's
  arbitration verdicts, which does not exist yet. Recomputing from scratch
  from `self.trace` each time is less efficient but requires no new state
  to keep consistent, appropriate for this RFC's deliberately provisional
  scope.
- **Letting an agent declare its own confidence tier**: rejected outright —
  this is exactly the self-assertion RFC-0002 already refused to allow.

## Backward compatibility

Additive only. `NexusCore(trust=None)` (the default) reproduces every
existing test's "first match" behavior exactly — this RFC changes nothing
for a caller who does not opt in.

## Open questions

- `lessons.py`'s `Lesson` has no `agent_id` field today — recurrence
  penalties (§3) cannot actually be attributed to a specific agent until
  one is added. Tracked as a follow-up to this RFC, not blocking it: the
  reference implementation accepts `recurrences` as a plain integer the
  caller supplies, so the attribution mechanism can be added to `lessons.py`
  independently.
- Should `score_from_evidence` decay older evidence (a claim verified two
  years ago counts less today)? Left out for now — no evidence has enough
  age yet in this project for the question to be answerable from real data;
  revisit once `AuditLog` timestamps span a meaningful period.
- This RFC computes trust by rescanning `NexusCore.trace` on every
  `route()` call when candidates tie — fine at this project's current
  scale, a real performance concern once agent/task volume grows. Not
  addressed here; Level 9 (Observability) is the more natural home for a
  cached/incremental version once it matters.
