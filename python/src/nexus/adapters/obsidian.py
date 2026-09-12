"""Level 5/12 knowledge connector — reads and writes Obsidian-compatible
Markdown notes (YAML frontmatter + body) in a vault directory.

An Obsidian vault is just a folder of Markdown files, so this adapter needs
no Obsidian installation to use or test: any vault it writes to opens
correctly in the real app.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..protocol import Evidence

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def _safe_stem(value: str) -> str:
    """Filesystem-safe filename stem. `task_id` reaches this method from
    wherever a `Task` came from — including, via `nexus.a2a.a2a_message_to_task`,
    an incoming A2A message's `taskId` field, which this module has no
    control over. A `task_id` of e.g. `"../../../../etc/passwd"` used
    unsanitized in a path join escapes the vault directory entirely.
    Excluding '.' outright (unlike a scheme that keeps it and only rejects
    the literal '..' segment) means a run of dots can't reconstitute a
    traversal sequence after substitution."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    return safe or "note"


class ObsidianVault:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def write_evidence_note(self, evidence: Evidence, task_id: str) -> Path:
        """One note per evidence entry (RFC-0001 §5) — the provenance chain
        becomes a browsable, linkable Obsidian note instead of living only
        inside a JSON envelope."""
        agent_suffix = _safe_stem(evidence.agent_id.split(":")[-1][:8])
        note_path = self.path / f"{_safe_stem(task_id)}-{agent_suffix}.md"
        frontmatter_lines = [
            "---",
            f"task_id: {task_id}",
            f"agent_id: {evidence.agent_id}",
            f"source: {evidence.source}",
            f"confidence: {evidence.confidence}",
            f"transformation: {evidence.transformation}",
            f"retrieved_at: {evidence.retrieved_at}",
            "tags: [nexus, evidence]",
            "---",
            "",
        ]
        body_lines = [f"# {evidence.claim}", ""]
        if evidence.location:
            body_lines.append(f"**Location:** {evidence.location}")
        body_lines.append(f"**Source:** {evidence.source}")
        note_path.write_text("\n".join(frontmatter_lines + body_lines) + "\n", encoding="utf-8")
        return note_path

    def read_note(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        match = FRONTMATTER_RE.match(text)
        if not match:
            return {"frontmatter": {}, "body": text}
        raw_frontmatter, body = match.groups()
        frontmatter: dict[str, str] = {}
        for line in raw_frontmatter.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                frontmatter[key.strip()] = value.strip()
        return {"frontmatter": frontmatter, "body": body}

    def list_notes(self) -> list[Path]:
        return sorted(self.path.glob("*.md"))
