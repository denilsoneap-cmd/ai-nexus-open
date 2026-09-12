# RFC Process

Significant changes to AI Nexus Open — protocol changes, new core subsystems,
breaking changes, governance or license changes — go through an RFC (Request
for Comments).

## Why

The Nexus Protocol is meant to be implemented by people who never read this
repository's code. It has to be stable, deliberate, and documented for that to
work. RFCs are how that stability is maintained without freezing the project.

## Process

```
RFC -> Proposal -> Discussion -> Review -> Vote -> Release
```

1. **Draft** — copy [0000-template.md](0000-template.md) to
   `NNNN-short-title.md` using the next available number, fill it in.
2. **Proposal** — open a PR adding the file. This is the formal proposal.
3. **Discussion** — open discussion on the PR. The author revises the RFC in
   place based on feedback.
4. **Review** — once discussion settles, maintainers (or the TSC, once formed)
   review it against [ARCHITECTURE.md](../../ARCHITECTURE.md).
5. **Vote** — maintainers vote to accept, reject, or request changes.
6. **Release** — an accepted RFC is merged with status `Accepted` and tracked
   in [ROADMAP.md](../../ROADMAP.md); implementation can begin.

## Status values

`Draft` -> `Proposed` -> `Accepted` | `Rejected` -> `Superseded` (if replaced
by a later RFC).

## Numbering

RFCs are numbered sequentially starting at `0001`. `0000` is reserved for the
template itself.
