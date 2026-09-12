"""Level 5 (Memory + Knowledge) — a "lessons learned" store: one agent's
mistake becomes a permanent, mechanism-backed rule every future agent
consults before acting.

Ported faithfully from this project's own prior work at
`Mif-Oracle/scripts/agente_auditor.py` and `Mif-Oracle/.claude/licoes/*.json`
— including its central design principle, carried over almost verbatim from
that project's own refusal message:

    "Conselho não impede nada. Mecanismo impede."
    ("Advice doesn't prevent anything. A mechanism does.")

`LessonStore.record()` refuses a lesson unless its correction names a real,
checkable mechanism — a test, a lint rule, a hook, a guide/skill doc, or a
permission/sandbox restriction. "Be more careful next time" is not accepted
as a fix. This is the same principle as ARCHITECTURE.md #4 (evidence before
trust) applied to an agent's own claimed fixes: "this prevents recurrence"
is a claim that needs its own evidence (the mechanism), not just an
assertion.

Recording the same symptom twice increments `recurrences` instead of
duplicating the lesson — a repeat means the mechanism didn't hold, which
`compile_digest()` surfaces first and marks REPEATED, matching the source
project's own prioritization.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

LAYERS = ["Guides", "Sensors", "Tools", "Constraints", "Memory"]

MECHANISM_PATTERNS = {
    "test": r"(?i)\b(test|utplsql|pytest|suite|assert)",
    "lint": r"(?i)\b(lint|rule [A-Za-z]?\d{2,3}|ruff|eslint)",
    "hook": r"(?i)\b(hook|settings\.json|pretooluse|pre-commit)",
    "guide": r"(?i)\b(claude\.md|guide|skill|readme)",
    "restriction": r"(?i)\b(permission|allowlist|sandbox|worktree)",
}

EMPTY_PHRASES = [
    r"(?i)be (more )?careful", r"(?i)pay (more )?attention", r"(?i)remember to",
    r"(?i)don'?t forget", r"(?i)review (it )?more carefully", r"(?i)be more attentive",
]


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60] or "lesson"


def classify_mechanism(correction: str) -> str | None:
    for name, pattern in MECHANISM_PATTERNS.items():
        if re.search(pattern, correction):
            return name
    return None


def is_vague(correction: str) -> bool:
    return any(re.search(p, correction) for p in EMPTY_PHRASES)


class LessonRejected(ValueError):
    pass


@dataclass
class Lesson:
    signature: str
    symptom: str
    correction: str
    mechanism: str
    layer: str
    rule: str
    cause: str = ""
    recorded_at: str = field(default_factory=lambda: date.today().isoformat())
    recurrences: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Lesson":
        return Lesson(**d)


class LessonStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def record(
        self, symptom: str, correction: str, rule: str | None = None,
        layer: str = "Guides", cause: str = "",
    ) -> Lesson:
        if is_vague(correction):
            raise LessonRejected(
                f"correction is advice, not a mechanism: {correction!r}. "
                "A lesson needs a test, lint rule, hook, guide, or restriction."
            )
        mechanism = classify_mechanism(correction)
        if mechanism is None:
            raise LessonRejected(f"correction names no recognizable mechanism: {correction!r}")
        if layer not in LAYERS:
            layer = "Guides"

        signature = _slug(symptom)
        existing = self._load(signature)
        if existing is not None:
            existing.recurrences += 1
            self._save(existing)
            return existing

        lesson = Lesson(
            signature=signature, symptom=symptom, correction=correction,
            mechanism=mechanism, layer=layer, rule=rule or symptom, cause=cause,
        )
        self._save(lesson)
        return lesson

    def _file(self, signature: str) -> Path:
        return self.path / f"{signature}.json"

    def _load(self, signature: str) -> Lesson | None:
        file = self._file(signature)
        if not file.exists():
            return None
        return Lesson.from_dict(json.loads(file.read_text(encoding="utf-8")))

    def _save(self, lesson: Lesson) -> None:
        self._file(lesson.signature).write_text(
            json.dumps(lesson.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def all(self) -> list[Lesson]:
        return [Lesson.from_dict(json.loads(p.read_text(encoding="utf-8")))
                for p in sorted(self.path.glob("*.json"))]

    def compile_digest(self) -> str:
        """The equivalent of Mif-Oracle's `LICOES.md`: a Markdown digest
        meant to be injected into every agent's context at session start
        (see that project's `.claude/hooks/carregar-licoes.sh`), so one
        agent's mistake becomes every future agent's knowledge."""
        lessons = self.all()
        if not lessons:
            return "# Lessons\n\nNo lessons recorded yet.\n"

        lines = [
            "# Lessons",
            "",
            "Generated file — do not hand-edit. Every lesson here came from a "
            "real mistake that already happened. None of them may happen again.",
            "",
        ]
        by_layer: dict[str, list[Lesson]] = {}
        for lesson in lessons:
            by_layer.setdefault(lesson.layer, []).append(lesson)

        for layer in LAYERS:
            items = by_layer.get(layer)
            if not items:
                continue
            lines.append(f"## {layer}")
            lines.append("")
            for lesson in sorted(items, key=lambda entry: -entry.recurrences):
                mark = " **[REPEATED]**" if lesson.recurrences else ""
                lines.append(f"### {lesson.rule}{mark}")
                lines.append("")
                lines.append(f"- **Observed symptom:** {lesson.symptom}")
                if lesson.cause:
                    lines.append(f"- **Cause:** {lesson.cause}")
                lines.append(
                    f"- **Mechanism that prevents recurrence:** {lesson.correction} "
                    f"(type: {lesson.mechanism})"
                )
                lines.append(f"- **Recorded:** {lesson.recorded_at}")
                if lesson.recurrences:
                    lines.append(
                        f"- **Recurrences:** {lesson.recurrences}. The previous "
                        "mechanism did not hold — treat with priority."
                    )
                lines.append("")

        repeated = sum(1 for lesson in lessons if lesson.recurrences)
        lines.append("---")
        lines.append("")
        lines.append(f"{len(lessons)} lesson(s) on file. {repeated} repeated.")
        return "\n".join(lines)
