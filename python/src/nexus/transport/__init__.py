"""Message Bus bindings — how Nexus's A2A Message/Task shapes (see
`nexus.a2a`) actually move between agent instances. RFC-0003 defers to A2A's
own specified bindings (JSON-RPC, gRPC, HTTP+REST) for real interop; modules
in this package are additional bindings for cases those don't fit (e.g. two
agents on the same machine with no network stack running between them),
carrying the same payload shapes.
"""
