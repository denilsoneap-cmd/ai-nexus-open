# Contributing

Thanks for considering a contribution to AI Nexus Open.

## Before you write code

Check [ARCHITECTURE.md](ARCHITECTURE.md) — every contribution should respect
the vendor-neutrality and protocol-over-implementation principles there. A PR
that hardcodes a specific model or framework into the core will be redirected
to an adapter instead.

## Small changes

Bug fixes, documentation, typos, small non-breaking improvements: open a PR
directly. No RFC needed.

## Significant changes

Anything that changes the protocol, adds a new core subsystem, breaks
compatibility, or changes governance/license: write an RFC first. See
[docs/rfcs/README.md](docs/rfcs/README.md) for the process and
[docs/rfcs/0000-template.md](docs/rfcs/0000-template.md) for the template.

Do not start implementation of a significant change before its RFC is
accepted — it may be redesigned or rejected in review, and unreviewed
implementation work is likely to be wasted.

## Code style

- Keep changes focused; do not mix an RFC's implementation with unrelated
  refactors.
- New subsystems that reach maturity are expected to move to their own
  repository under the `ai-nexus-open` GitHub organization (see
  [ARCHITECTURE.md](ARCHITECTURE.md#layer-breakdown)); this repo hosts the
  spec, manifesto, and Genesis-level docs.

## Code of conduct

Be respectful. Disagreement about technical direction is expected and
welcome — it happens through RFCs, not through personal conflict.
