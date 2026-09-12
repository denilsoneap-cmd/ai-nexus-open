import pytest

from nexus.adapters.lessons import LessonRejected, LessonStore, classify_mechanism, is_vague


def test_classify_mechanism_recognizes_each_type():
    assert classify_mechanism("Added a pytest regression test") == "test"
    assert classify_mechanism("Rewrote lint rule R011") == "lint"
    assert classify_mechanism("Added a PreToolUse hook in settings.json") == "hook"
    assert classify_mechanism("Documented it in CLAUDE.md") == "guide"
    assert classify_mechanism("Removed write permission via sandbox") == "restriction"
    assert classify_mechanism("Told the team to be careful") is None


def test_is_vague_detects_empty_phrases():
    assert is_vague("Be more careful next time") is True
    assert is_vague("Added a lint rule to catch this") is False


def test_record_rejects_vague_correction(tmp_path):
    store = LessonStore(tmp_path)
    with pytest.raises(LessonRejected):
        store.record(symptom="Agent broke prod", correction="Remember to be careful")


def test_record_rejects_correction_with_no_mechanism(tmp_path):
    store = LessonStore(tmp_path)
    with pytest.raises(LessonRejected):
        store.record(symptom="Agent broke prod", correction="We had a discussion about it")


def test_record_succeeds_with_real_mechanism(tmp_path):
    store = LessonStore(tmp_path)
    lesson = store.record(
        symptom="Agent ran DDL directly against production",
        correction="PreToolUse hook in settings.json blocks commands against the prod alias",
        layer="Constraints",
        rule="No agent touches production. Staging only.",
    )
    assert lesson.mechanism == "hook"
    assert lesson.recurrences == 0
    assert (tmp_path / f"{lesson.signature}.json").exists()


def test_recording_same_symptom_twice_increments_recurrences(tmp_path):
    store = LessonStore(tmp_path)
    store.record(symptom="Agent ran DDL directly against production",
                 correction="Added a hook blocking prod commands")
    second = store.record(symptom="Agent ran DDL directly against production",
                           correction="Hardened the hook further")
    assert second.recurrences == 1
    assert len(store.all()) == 1  # not duplicated


def test_all_lists_every_recorded_lesson(tmp_path):
    store = LessonStore(tmp_path)
    store.record(symptom="A", correction="Added a test for A")
    store.record(symptom="B", correction="Added a lint rule for B")
    assert {lesson.symptom for lesson in store.all()} == {"A", "B"}


def test_compile_digest_groups_by_layer_and_marks_repeats(tmp_path):
    store = LessonStore(tmp_path)
    store.record(symptom="Repeats a lot", correction="Added a hook", layer="Constraints")
    store.record(symptom="Repeats a lot", correction="Hardened the hook", layer="Constraints")
    store.record(symptom="Only once", correction="Added a test", layer="Sensors")

    digest = store.compile_digest()
    assert "## Constraints" in digest
    assert "## Sensors" in digest
    assert "[REPEATED]" in digest
    assert "2 lesson(s) on file. 1 repeated." in digest


def test_compile_digest_empty_store(tmp_path):
    store = LessonStore(tmp_path)
    assert "No lessons recorded yet" in store.compile_digest()


def test_lessons_persist_across_store_instances(tmp_path):
    LessonStore(tmp_path).record(symptom="X", correction="Added a test for X")
    reopened = LessonStore(tmp_path)
    assert len(reopened.all()) == 1


def test_record_attributes_agent_id(tmp_path):
    store = LessonStore(tmp_path)
    lesson = store.record(symptom="X", correction="Added a test for X", agent_id="agent:a")
    assert lesson.agent_id == "agent:a"


def test_recurrence_does_not_reattribute_agent_id(tmp_path):
    store = LessonStore(tmp_path)
    store.record(symptom="X", correction="Added a test for X", agent_id="agent:a")
    second = store.record(symptom="X", correction="Hardened the test", agent_id="agent:b")
    assert second.recurrences == 1
    assert second.agent_id == "agent:a"  # first attribution is kept, not overwritten


def test_recurrences_for_sums_across_lessons_attributed_to_the_agent(tmp_path):
    store = LessonStore(tmp_path)
    store.record(symptom="X", correction="Added a test for X", agent_id="agent:a")
    store.record(symptom="X", correction="Hardened the test", agent_id="agent:a")  # recurrence -> 1
    store.record(symptom="Y", correction="Added a lint rule for Y", agent_id="agent:a")
    store.record(symptom="Y", correction="Hardened the lint rule", agent_id="agent:a")  # recurrence -> 1
    store.record(symptom="Z", correction="Added a hook for Z", agent_id="agent:b")

    assert store.recurrences_for("agent:a") == 2
    assert store.recurrences_for("agent:b") == 0
    assert store.recurrences_for("agent:unknown") == 0


def test_recurrences_for_ignores_lessons_with_no_agent_id(tmp_path):
    store = LessonStore(tmp_path)
    store.record(symptom="X", correction="Added a test for X")  # no agent_id
    store.record(symptom="X", correction="Hardened the test")
    assert store.recurrences_for("agent:a") == 0
