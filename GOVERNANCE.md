# Governance

AI Nexus Open is built to be a community project, not a personal one. This
document describes how decisions get made while the project is small, and how
that structure is expected to grow.

## Roles

```
Founder / Initial Maintainer
          |
Technical Steering Committee (TSC)
          |
     Maintainers
          |
    Contributors
          |
     Community
```

- **Founder / Initial Maintainer** — holds final say only until a TSC exists;
  the explicit goal is to dissolve this single point of authority as the
  project gains contributors.
- **Technical Steering Committee (TSC)** — approves RFCs, sets technical
  direction, formed once there are enough active maintainers to staff it.
- **Maintainers** — merge rights on one or more repositories under the org.
- **Contributors** — anyone with a merged PR or an accepted RFC.
- **Community** — anyone using or discussing the project.

## Decision process

Non-trivial changes (protocol changes, new core subsystems, breaking changes,
license/governance changes) go through an RFC — see
[docs/rfcs/README.md](docs/rfcs/README.md). Routine changes (bug fixes, docs,
small features) go through normal PR review.

```
RFC -> Proposal -> Discussion -> Review -> Vote -> Release
```

## Adding a maintainer

A contributor becomes a maintainer by sustained, quality contribution and a
nomination approved by existing maintainers (or the Founder, before a TSC
exists). This is intentionally informal at this stage; it will be formalized
as an RFC once the contributor base justifies it.

## Scope of this document

This is a starting point, not a constitution. It should itself be amended by
RFC as the project grows — see RFC-0000 template for the process.
