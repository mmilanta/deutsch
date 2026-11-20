import io
import json
import re

import pytest
from rich.console import Console

from deutsch.core import Exercise
from deutsch.difficulty import GameOptions
from deutsch.history import load_history
from deutsch.tui import DeutschApp


def exercise():
    return Exercise(word_id="gehen", sentence_id="gehen-01", infinitive="gehen",
                    italian="Io vado.", italian_target="vado", german="Ich gehe.", german_target="gehe")


def app_for(tmp_path, answers, **kwargs):
    output = io.StringIO()
    lines = iter(answers)
    deck = [exercise().model_copy(update={"sentence_id": f"gehen-{i:02}"}) for i in range(1, 4)]
    app = DeutschApp(deck, tmp_path / "guesses.jsonl", console=Console(file=output, color_system=None),
                     read_line=lambda: next(lines), **kwargs)
    return app, output


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_reveal_and_quit_are_events_not_guesses(tmp_path):
    app, _ = app_for(tmp_path, ["", "/q"])
    app.run()
    events = records(tmp_path / "guesses.events.jsonl")
    assert [e["event"] for e in events] == ["presented", "gave_up", "presented", "abandoned"]
    assert events[0]["presentation_id"] == events[1]["presentation_id"]
    assert events[0]["presentation_id"] != events[2]["presentation_id"]
    assert not (tmp_path / "guesses.jsonl").exists()
    assert [p.score for p in load_history(tmp_path / "guesses.jsonl").presentations] == [0, None]


def test_guess_ids_link_to_one_presentation_and_retry_does_not_override_failure(tmp_path):
    app, _ = app_for(tmp_path, ["  kommen  ", "GEHEN", "/q"])
    app.run()
    guesses = records(tmp_path / "guesses.jsonl")
    assert guesses[0]["guess"] == "  kommen  "
    assert guesses[0]["schema_version"] == 2
    assert guesses[0]["presentation_id"] == guesses[1]["presentation_id"]
    history = load_history(tmp_path / "guesses.jsonl")
    assert [p.score for p in history.presentations] == [0, None]
    assert [p.score for p in app.history.presentations] == [0, None]


@pytest.mark.parametrize("exception", [EOFError, KeyboardInterrupt])
def test_interrupt_closes_presentation_without_inventing_failure(tmp_path, exception):
    app, _ = app_for(tmp_path, [])

    def stop():
        raise exception

    app.read_line = stop
    app.run()
    assert records(tmp_path / "guesses.events.jsonl")[-1]["event"] == "abandoned"
    assert load_history(tmp_path / "guesses.jsonl").presentations[0].score is None


def test_failed_initial_event_write_stops_without_collecting_unlogged_answers(tmp_path):
    app, output = app_for(tmp_path, ["gehen"], events_path=tmp_path)
    app.run()
    assert "Salvataggio non riuscito" in output.getvalue()
    assert app.guesses == 0
    assert not (tmp_path / "guesses.jsonl").exists()


def test_failed_terminal_event_write_is_visible_and_session_stops(tmp_path, monkeypatch):
    from deutsch.tui import append_event

    def fail_at_finish(*args, **kwargs):
        if args[4] != "presented":
            raise OSError("test event write failure")
        return append_event(*args, **kwargs)

    monkeypatch.setattr("deutsch.tui.append_event", fail_at_finish)
    app, output = app_for(tmp_path, ["gehen"])
    app.run()
    assert "Evento non salvato" in output.getvalue()
    assert app.correct == 1
    assert load_history(tmp_path / "guesses.jsonl").presentations[0].score == 1


def test_difficulty_and_answer_stay_hidden_until_reveal(tmp_path):
    app, output = app_for(tmp_path, ["/q"], difficulty={"gehen-01": 1.25})
    app.run()
    assert "gehen" not in output.getvalue()
    assert "difficoltà:" not in output.getvalue()


@pytest.mark.parametrize("answer", ["gehen", ""])
def test_signed_difficulty_is_shown_with_revealed_answer(tmp_path, answer):
    app, output = app_for(tmp_path, [answer, "/q"], difficulty={"gehen-01": -1.25})
    app.run()
    text = output.getvalue()
    assert "Ich gehe.  · difficoltà: -1.250\ninfinito: gehen\n" in text
    assert text.count("difficoltà:") == 1
    assert text.index("Io vado.") < text.index("difficoltà:")
    assert not re.search(r"\n\n-+|-+\n\n", text)


def test_missing_difficulty_is_not_displayed_as_a_fake_number(tmp_path):
    app, output = app_for(tmp_path, [])
    app.reveal(exercise())
    assert "difficoltà: n/d" in output.getvalue()


def test_losing_last_life_stops_without_presenting_next_sentence(tmp_path):
    app, output = app_for(tmp_path, [""], options=GameOptions(lives=1),
                          difficulty={"gehen-01": 2.0, "gehen-02": -1.0})
    app.run()
    assert "Vite esaurite." in output.getvalue()
    assert app.lives_left == 0
    events = records(app.events_path)
    assert [e["event"] for e in events] == ["presented", "gave_up"]
    assert events[0]["sentence_id"] == "gehen-02"
