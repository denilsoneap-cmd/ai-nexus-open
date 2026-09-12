"""Adapters plug external systems into Nexus without becoming the core.

Per ARCHITECTURE.md principle 1 (vendor neutrality), nothing in `nexus.core`
imports from this package. Each adapter either produces an `Agent` that
registers with `NexusCore` like any other, or is an optional, explicitly
injected dependency (e.g. `NexusCore(graph=...)`).
"""
