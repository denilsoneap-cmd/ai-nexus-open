from nexus.adapters.obsidian import ObsidianVault
from nexus.protocol import Evidence


def make_evidence() -> Evidence:
    return Evidence(
        claim="The ICMS-ST rate for this product in MG is 18%.",
        source="official.gov.br",
        agent_id="agent:tax001",
        transformation="extracted_verbatim",
        confidence=0.97,
        location="Article 15",
    )


def test_write_evidence_note_creates_readable_markdown(tmp_path):
    vault = ObsidianVault(tmp_path / "vault")
    note_path = vault.write_evidence_note(make_evidence(), task_id="task-123")

    assert note_path.exists()
    text = note_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "task_id: task-123" in text
    assert "# The ICMS-ST rate for this product in MG is 18%." in text


def test_read_note_parses_frontmatter_and_body(tmp_path):
    vault = ObsidianVault(tmp_path / "vault")
    note_path = vault.write_evidence_note(make_evidence(), task_id="task-123")

    parsed = vault.read_note(note_path)
    assert parsed["frontmatter"]["task_id"] == "task-123"
    assert parsed["frontmatter"]["confidence"] == "0.97"
    assert "ICMS-ST" in parsed["body"]


def test_list_notes_returns_all_markdown_files(tmp_path):
    vault = ObsidianVault(tmp_path / "vault")
    vault.write_evidence_note(make_evidence(), task_id="task-1")
    vault.write_evidence_note(make_evidence(), task_id="task-2")

    notes = vault.list_notes()
    assert len(notes) == 2
    assert all(p.suffix == ".md" for p in notes)


def test_vault_directory_is_created_if_missing(tmp_path):
    vault_path = tmp_path / "does" / "not" / "exist"
    ObsidianVault(vault_path)
    assert vault_path.is_dir()
