"""Level 12 (Graph Intelligence) — a minimal edge store, schema-compatible
with the `graph_edges` table already running in this workspace's Ruflo
instance (`.swarm/schema.sql`, ADR-130: "unified knowledge graph backend").

This store is intentionally separate from Ruflo's live `.swarm/memory.db` —
Nexus does not write into another system's production database as a side
effect of running tests or examples. The schema is a deliberate mirror so
that pointing `GraphStore` at that same file later (a real Level-2 Ruflo
integration) is a configuration change, not a migration.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_edges (
  id              TEXT PRIMARY KEY,
  source_id       TEXT NOT NULL,
  target_id       TEXT NOT NULL,
  relation        TEXT NOT NULL,
  weight          REAL DEFAULT 1.0,
  confidence      REAL DEFAULT 1.0,
  decay_rate      REAL DEFAULT 0.0,
  last_reinforced TEXT,
  witness_id      TEXT,
  embedding_ref   TEXT,
  metadata        TEXT,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source   ON graph_edges (source_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target   ON graph_edges (target_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_relation ON graph_edges (relation);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GraphStore:
    """Node IDs are expected in the domain-prefixed form used across this
    project (RFC-0002 §1): ``{domain}:{id}`` — e.g. ``agent:...``,
    ``task:...``, ``evidence:...``. This store does not enforce that; it is
    a convention callers (like `NexusCore`) follow."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        edge_id = f"edge-{uuid.uuid4().hex[:12]}"
        self._conn.execute(
            "INSERT INTO graph_edges "
            "(id, source_id, target_id, relation, weight, confidence, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                edge_id,
                source_id,
                target_id,
                relation,
                weight,
                confidence,
                json.dumps(metadata) if metadata else None,
                _now_iso(),
            ),
        )
        self._conn.commit()
        return edge_id

    def _rows_to_dicts(self, rows: list[tuple]) -> list[dict[str, Any]]:
        cols = ["id", "source_id", "target_id", "relation", "weight", "confidence",
                "decay_rate", "last_reinforced", "witness_id", "embedding_ref",
                "metadata", "created_at"]
        out = []
        for row in rows:
            d = dict(zip(cols, row))
            if d["metadata"]:
                d["metadata"] = json.loads(d["metadata"])
            out.append(d)
        return out

    def edges_from(self, source_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM graph_edges WHERE source_id = ?", (source_id,))
        return self._rows_to_dicts(cur.fetchall())

    def edges_to(self, target_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM graph_edges WHERE target_id = ?", (target_id,))
        return self._rows_to_dicts(cur.fetchall())

    def edges_by_relation(self, relation: str, limit: int | None = None) -> list[dict[str, Any]]:
        """All edges of one `relation` type, most recently created first —
        e.g. every `"won"` edge a `NexusCore(graph=...)` debate has ever
        recorded, for a caller building a report across many past runs
        rather than looking up one specific node."""
        query = "SELECT * FROM graph_edges WHERE relation = ? ORDER BY created_at DESC"
        params: tuple[Any, ...] = (relation,)
        if limit is not None:
            query += " LIMIT ?"
            params = (relation, limit)
        cur = self._conn.execute(query, params)
        return self._rows_to_dicts(cur.fetchall())

    def close(self) -> None:
        self._conn.close()
