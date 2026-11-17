import json
from datetime import datetime, timezone

from deutsch.core import Exercise, append_guess
from deutsch.history import append_event, events_path_for, load_history


def exercise():
    return Exercise(word_id="gehen", sentence_id="gehen-01", infinitive="gehen",
                    italian="Io vado.", italian_target="vado", german="Ich gehe.", german_target="gehe")


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def guess(attempt=1, result="incorrect", **extra):
    return dict(schema_version=1, timestamp="2026-01-01T12:00:00+00:00", session_id="s",
                word_id="gehen", sentence_id="gehen-01", expected_infinitive="gehen",
                attempt=attempt, result=result, **extra)


def test_empty_history_does_not_create_files(tmp_path):
    path = tmp_path / "guesses.jsonl"
    assert load_history(path).presentations == []
    assert list(tmp_path.iterdir()) == []
    assert events_path_for(path) == tmp_path / "guesses.events.jsonl"


def test_legacy_retries_form_one_observation(tmp_path):
    path = tmp_path / "guesses.jsonl"
    write_rows(path, [guess(), guess(2, "almost_there"), guess(3, "correct")])
    before = path.read_bytes()
    history = load_history(path)
    assert len(history.presentations) == 1
    observation = history.presentations[0]
    assert observation.score == 0
    assert observation.legacy
    assert not observation.gave_up  # An old give-up must never be invented.
    assert path.read_bytes() == before


def test_missing_first_attempt_is_not_inferred_from_a_successful_retry(tmp_path):
    path = tmp_path / "guesses.jsonl"
    write_rows(path, [guess(2, "correct")])
    assert load_history(path).presentations[0].score is None


def test_legacy_attempt_reset_session_and_intervening_word_split_presentations(tmp_path):
    path = tmp_path / "guesses.jsonl"
    first = guess(result="correct")
    other_word = first | {"word_id": "kommen", "sentence_id": "kommen-01"}
    other_session = first | {"session_id": "other"}
    write_rows(path, [first, first, other_word, first, other_session])
    assert len(load_history(path).presentations) == 5


def test_new_guesses_and_events_are_deduplicated(tmp_path):
    path, events = tmp_path / "guesses.jsonl", tmp_path / "events.jsonl"
    ex = exercise()
    append_event(events, ex, "s", "p", "presented")
    append_guess(path, ex, "  gehn  ", "s", 1, presentation_id="p")
    append_guess(path, ex, "gehen", "s", 2, presentation_id="p")
    append_event(events, ex, "s", "p", "completed", attempts=2, first_result="almost_there")
    history = load_history(path, events)
    assert len(history.presentations) == 1
    assert history.presentations[0].score == 0.5
    assert not history.presentations[0].legacy
    assert not history.warnings
    assert json.loads(path.read_text().splitlines()[0])["guess"] == "  gehn  "


def test_reveal_without_guess_and_quit_have_different_meaning(tmp_path):
    events, path = tmp_path / "events.jsonl", tmp_path / "guesses.jsonl"
    ex = exercise()
    for identifier, end in [("a", "gave_up"), ("b", "abandoned"), ("c", None)]:
        append_event(events, ex, "s", identifier, "presented")
        if end:
            append_event(events, ex, "s", identifier, end)
    history = load_history(path, events)
    assert [p.score for p in history.presentations] == [0.0, None, None]
    assert len(history.for_word("gehen", "gehen")) == 3
    assert not path.exists()


def test_reveal_after_near_miss_is_not_mastery(tmp_path):
    path, events, ex = tmp_path / "guesses.jsonl", tmp_path / "events.jsonl", exercise()
    append_guess(path, ex, "gehn", "s", 1, presentation_id="p")
    append_event(events, ex, "s", "p", "gave_up", attempts=1, first_result="almost_there")
    assert load_history(path, events).presentations[0].score == 0


def test_interrupted_presentation_keeps_first_attempt_evidence(tmp_path):
    path, events, ex = tmp_path / "guesses.jsonl", tmp_path / "events.jsonl", exercise()
    append_event(events, ex, "s", "p", "presented")
    append_guess(path, ex, "kommen", "s", 1, presentation_id="p")
    assert load_history(path, events).presentations[0].score == 0


def test_terminal_event_recovers_evidence_if_guess_file_is_missing(tmp_path):
    path, events = tmp_path / "guesses.jsonl", tmp_path / "events.jsonl"
    append_event(events, exercise(), "s", "p", "completed", attempts=1, first_result="correct")
    assert load_history(path, events).presentations[0].score == 1


def test_bad_lines_and_future_schemas_warn_without_rewriting(tmp_path):
    path = tmp_path / "guesses.jsonl"
    write_rows(path, [guess(), {"schema_version": 99}, {"result": "wrong"}])
    with path.open("a") as file:
        file.write('{"truncated":')
    before = path.read_bytes()
    history = load_history(path)
    assert len(history.presentations) == 1
    assert len(history.warnings) == 3
    assert path.read_bytes() == before


def test_conflicting_presentation_metadata_is_ignored(tmp_path):
    path = tmp_path / "guesses.jsonl"
    first = guess(presentation_id="p")
    write_rows(path, [first, first | {"word_id": "other", "attempt": 2, "result": "correct"}])
    history = load_history(path)
    assert len(history.presentations) == 1
    assert history.presentations[0].score == 0
    assert len(history.warnings) == 1


def test_history_does_not_reuse_answer_for_changed_infinitive(tmp_path):
    path = tmp_path / "guesses.jsonl"
    write_rows(path, [guess(result="correct")])
    assert load_history(path).for_word("gehen", "kommen") == []


def test_naive_old_timestamps_are_interpreted_as_utc(tmp_path):
    path = tmp_path / "guesses.jsonl"
    write_rows(path, [guess() | {"timestamp": "2026-01-01T12:00:00"}])
    assert load_history(path).presentations[0].timestamp == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
