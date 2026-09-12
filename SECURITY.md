# Security Policy

## Supported versions

Pre-1.0: only the `main` branch is supported. There is no released package
on any index yet (`nexus-sdk` in [`python/pyproject.toml`](python/pyproject.toml)
is version `0.1.0`, installed locally via `pip install -e .` — not published
to PyPI). Once a numbered release process exists, this section will name
which versions still receive fixes.

## Reporting a vulnerability

Use **GitHub's private vulnerability reporting**, not a public issue:
[github.com/denilsoneap-cmd/ai-nexus-open/security/advisories/new](https://github.com/denilsoneap-cmd/ai-nexus-open/security/advisories/new).
This opens a draft security advisory visible only to maintainers until it's
resolved, so a real vulnerability isn't disclosed publicly before a fix
exists.

If that link doesn't work for you for any reason, open a regular issue
asking for a private channel — do not post exploit details in a public
issue or PR.

## What counts

This project is a young reference implementation (see [ROADMAP.md](ROADMAP.md)),
not a hardened production system — but real vulnerabilities in it are still
real vulnerabilities. In scope:

- Anything in [`python/src/nexus/`](python/src/nexus/) that lets data
  escape a sandbox it's supposed to stay in (path traversal, injection,
  deserialization of untrusted input) — this project has already found and
  fixed two of these itself (path traversal via an unsanitized `agent_id`/
  `task_id` in `nexus/transport/filesystem.py` and
  `nexus/adapters/obsidian.py`) and takes the class of bug seriously.
- Anything in `nexus/identity_crypto.py` or `nexus/audit.py` that weakens
  the integrity guarantees those modules claim (signature verification that
  accepts a forged signature, a hash chain that doesn't actually detect
  tampering).
- Anything in `nexus/policy.py` that lets a risk-gated task execute without
  the approval RFC-0006 says it needs — a policy bypass is a security bug,
  not a feature gap (see the fix in this project's own commit history for
  the `NexusCore.debate()` bypass found the same day RFC-0006 shipped).

Not in scope: the intentionally-unimplemented gaps this project already
documents in [ROADMAP.md](ROADMAP.md) and each RFC's own "Open Questions" —
e.g. `task.constraints` not being enforced yet, or a discovered
`FileRegistry` card not being signature-verified. Those are known, tracked
gaps, not surprises.

## Response

This is a single-maintainer project (see [GOVERNANCE.md](GOVERNANCE.md)) —
there is no SLA yet. A genuine report will be acknowledged and worked on;
please be patient and specific (what you found, how to reproduce it, what
you think the impact is).
