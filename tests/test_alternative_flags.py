import io
import json
from datetime import datetime

import pytest
from rich.console import Console

from deutsch.core import Exercise
from deutsch.history import load_history
from deutsch.review import alternative_log_for, append_alternative_flag
from deutsch.tui import DeutschApp


def previous_exercise():
    return Exercise(word_id="laufen", sentence_id="laufen-01", infinitive="laufen",
                    italian="Corro ogni mattina al parco.", italian_target="Corro",
                    german="Ich laufe jeden Morgen im Park.", german_target="laufe")


def current_exercise():
    return Exercise(word_id="gehen", sentence_id="gehen-01", infinitive="gehen",
                    italian="Vado a casa.", italian_target="Vado",
                    german="Ich gehe nach Hause.", german_target="gehe")


def app_for(tmp_path, answers, **kwargs):
    lines, output = iter(answers), io.StringIO()
    app = DeutschApp([previous_exercise(), current_exercise()], tmp_path / "guesses.jsonl",
                     console=Console(file=output, color_system=None, width=120),
                     read_line=lambda: next(lines), **kwargs)
    return app, output


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("command", ["/alternative", "/alt"])
@pytest.mark.parametrize("previous_answer", ["laufen", ""])
def test_command_flags_previous_completed_or_revealed_not_current(tmp_path, previous_answer, command):
    app, output = app_for(tmp_path, [previous_answer, command, "gehen"])
    assert app.practice(previous_exercise())
    assert app.practice(current_exercise())
    flags = records(app.alternative_log)
    guesses = records(app.log_path)
    events = records(app.events_path)
    assert len(flags) == 1
    flag = flags[0]
    assert flag["sentence_id"] == "laufen-01"
    assert flag["word_id"] == "laufen"
    assert flag["expected_infinitive"] == "laufen"
    assert flag["italian"] == previous_exercise().italian
    assert flag["german"] == previous_exercise().german
    assert flag["presentation_id"] == events[0]["presentation_id"]
    assert flag["presentation_id"] != guesses[-1]["presentation_id"]
    assert flag["session_id"] == app.session_id
    assert guesses[-1]["guess"] == "gehen" and guesses[-1]["attempt"] == 1
    assert all(record["guess"] not in {"/alternative", "/alt"} for record in guesses)
    assert output.getvalue().count(current_exercise().italian) == 1
    assert "precedente segnalato" in output.getvalue()
    assert app.guesses == (2 if previous_answer else 1)
    history = load_history(app.log_path)
    assert [p.score for p in history.presentations] == ([1, 1] if previous_answer else [0, 1])
    assert not history.warnings


@pytest.mark.parametrize("command", ["/alternative", "/alt"])
def test_no_previous_exercise_does_not_flag_current_or_count_guess(tmp_path, command):
    app, output = app_for(tmp_path, [command, "gehen"])
    assert app.practice(current_exercise())
    assert "Nessun esercizio precedente" in output.getvalue()
    assert not app.alternative_log.exists()
    assert app.guesses == 1
    assert records(app.log_path)[0]["attempt"] == 1


def test_duplicate_command_does_not_duplicate_flag(tmp_path):
    app, output = app_for(tmp_path, ["laufen", "/alternative", " /ALTERNATIVE ", " /ALT ", "gehen"])
    app.practice(previous_exercise())
    app.practice(current_exercise())
    assert len(records(app.alternative_log)) == 1
    assert "già segnalato" in output.getvalue()
    assert app.guesses == 2


def test_command_during_retry_still_flags_previous_and_preserves_current_failure(tmp_path):
    app, _ = app_for(tmp_path, ["laufen", "kommen", "/alternative", "gehen"])
    app.practice(previous_exercise())
    app.practice(current_exercise())
    assert [g["attempt"] for g in records(app.log_path)] == [1, 1, 2]
    assert [p.score for p in load_history(app.log_path).presentations] == [1, 0]
    assert records(app.alternative_log)[0]["word_id"] == "laufen"
    assert app.guesses == 3


def test_next_completed_exercise_becomes_previous_for_flagging(tmp_path):
    app, _ = app_for(tmp_path, ["laufen", "/alternative", "gehen", "/alternative", "/q"])
    app.practice(previous_exercise())
    app.practice(current_exercise())
    assert app.practice(previous_exercise()) is False
    assert [r["word_id"] for r in records(app.alternative_log)] == ["laufen", "gehen"]
    assert len({r["presentation_id"] for r in records(app.alternative_log)}) == 2
    assert app.guesses == 2


def test_flag_is_sentence_specific_even_when_the_same_word_has_another_meaning(tmp_path):
    clock = Exercise(word_id="laufen", sentence_id="laufen-clock", infinitive="laufen",
                     italian="L'orologio funziona.", italian_target="funziona",
                     german="Die Uhr läuft.", german_target="läuft", meaning="funzionare")
    before = clock.model_dump()
    app, _ = app_for(tmp_path, ["laufen", "/alt", "laufen"])
    app.practice(previous_exercise())
    app.practice(clock)
    flag = records(app.alternative_log)[0]
    assert flag["word_id"] == clock.word_id  # Same word, different context.
    assert flag["sentence_id"] == "laufen-01"
    assert flag["sentence_id"] != clock.sentence_id
    assert flag["italian"] == "Corro ogni mattina al parco."
    assert "meaning" not in flag  # Do not borrow the current sentence's sense.
    assert clock.model_dump() == before


def test_repeated_word_flags_the_previous_presentation_not_current(tmp_path):
    app, _ = app_for(tmp_path, ["laufen", "/alternative", "laufen"])
    app.practice(previous_exercise())
    app.practice(previous_exercise())
    guesses = records(app.log_path)
    assert records(app.alternative_log)[0]["presentation_id"] == guesses[0]["presentation_id"]
    assert guesses[0]["presentation_id"] != guesses[1]["presentation_id"]


def test_failed_flag_write_can_be_retried_without_losing_current_answer(tmp_path):
    path = tmp_path / "blocked"
    path.mkdir()
    app, output = app_for(tmp_path, ["laufen"], alternative_log=path)
    app.practice(previous_exercise())
    count = 0

    def answers():
        nonlocal count
        count += 1
        if count == 1:
            return "/alternative"  # Fails: path is still a directory.
        if count == 2:
            assert not app.flagged_presentations
            path.rmdir()
            return "/alternative"
        return "gehen"

    app.read_line = answers
    app.practice(current_exercise())
    assert "Segnalazione non riuscita" in output.getvalue()
    assert "precedente segnalato" in output.getvalue()
    assert len(records(path)) == 1
    assert app.guesses == 2
    assert records(app.log_path)[-1]["attempt"] == 1


@pytest.mark.parametrize("collision", ["guesses.jsonl", "guesses.events.jsonl"])
def test_flag_log_cannot_share_guess_or_event_path(tmp_path, collision):
    path = tmp_path / collision
    path.write_text("existing data\n")
    with pytest.raises(ValueError, match="different paths"):
        app_for(tmp_path, [], alternative_log=path)
    assert path.read_text() == "existing data\n"


def test_flags_are_append_only_context_snapshots_with_optional_meaning(tmp_path):
    path = tmp_path / "nested" / "flags.jsonl"
    exercise = Exercise(word_id="heissen", sentence_id="heissen-01", infinitive="heißen",
                        italian="Mi chiamo Marco.", italian_target="Mi chiamo",
                        german="Ich heiße Marco.", german_target="heiße", meaning="nome")
    append_alternative_flag(path, exercise, "session", "first")
    before = path.read_bytes()
    append_alternative_flag(path, exercise, "session", "second")
    assert path.read_bytes().startswith(before)
    first, second = records(path)
    assert first["event"] == "alternative_requested"
    assert first["meaning"] == "nome"
    assert first["german"] == "Ich heiße Marco."
    assert datetime.fromisoformat(first["timestamp"]).tzinfo is not None
    assert second["presentation_id"] == "second"
    assert "guess" not in first
    assert alternative_log_for(tmp_path / "custom.jsonl") == tmp_path / "custom.alternatives.jsonl"


def test_flags_do_not_automatically_accept_alternative_answers(tmp_path):
    app, _ = app_for(tmp_path, ["laufen", "/alternative", "rennen", "laufen"])
    app.practice(previous_exercise())
    app.practice(previous_exercise())
    assert [g["result"] for g in records(app.log_path)] == ["correct", "incorrect", "correct"]
    assert [p.score for p in load_history(app.log_path).presentations] == [1, 0]
