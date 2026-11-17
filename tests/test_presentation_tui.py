import io
import json
import re

import pytest
from rich.console import Console

from deutsch.core import Exercise
from deutsch.frequencies import Frequency, FrequencyTable
from deutsch.history import load_history
from deutsch.scheduler import AdaptiveDeck
from deutsch.tui import DeutschApp


def exercise():
    return Exercise(word_id="gehen", sentence_id="gehen-01", infinitive="gehen",
                    italian="Io vado.", italian_target="vado", german="Ich gehe.", german_target="gehe")


def app_for(tmp_path, answers, **kwargs):
    output = io.StringIO()
    lines = iter(answers)
    app = DeutschApp([exercise()], tmp_path / "guesses.jsonl", console=Console(file=output, color_system=None),
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


def test_optional_explanation_does_not_reveal_the_answer(tmp_path):
    table = FrequencyTable(built_at="test", corpus_tokens=10, sources=[], methodology="test",
                           words={"gehen": Frequency(infinitive="gehen", zipf=5, method="lemma_pos", corpus_count=10)})
    from deutsch.history import History
    deck = AdaptiveDeck([exercise()], table, History())
    app, output = app_for(tmp_path, ["/q"], deck=deck, explain=True)
    app.run()
    assert "no scored history" in output.getvalue()
    assert "gehen" not in output.getvalue()
    assert app.history is deck.history
    assert app.frequencies is table
    assert "popolarità:" not in output.getvalue()


def popularity_table(score=5.81):
    return FrequencyTable(built_at="test", corpus_tokens=1000, sources=[], methodology="test",
                          words={"gehen": Frequency(infinitive="gehen", zipf=score, method="lemma_pos", corpus_count=100)})


@pytest.mark.parametrize("answer", ["gehen", ""])
def test_popularity_is_shown_with_revealed_answer_not_next_prompt(tmp_path, answer):
    app, output = app_for(tmp_path, [answer, "/q"], frequencies=popularity_table())
    app.run()
    text = output.getvalue()
    assert "Ich gehe.  · popolarità: 5.810\ninfinito: gehen\n" in text
    assert text.count("popolarità:") == 1
    assert text.index("Io vado.") < text.index("popolarità:")
    assert not re.search(r"\n\n-+|-+\n\n", text)


@pytest.mark.parametrize("missing", ["no_table", "no_word", "stale", "no_evidence"])
def test_missing_frequency_is_not_displayed_as_a_fake_number(tmp_path, missing):
    table = popularity_table()
    if missing == "no_table":
        table = None
    elif missing == "no_word":
        table.words.clear()
    elif missing == "stale":
        table.words["gehen"].infinitive = "kommen"
    else:
        table.words["gehen"].method = "missing"
    app, output = app_for(tmp_path, [], frequencies=table)
    app.reveal(exercise())
    assert "popolarità: n/d" in output.getvalue()


def test_popularity_display_is_monotonic_in_frequency(tmp_path):
    app, output = app_for(tmp_path, [])
    scores = [0.0, 2.5, 4.125, 5.81, 6.001]
    for score in scores:
        app.frequencies = popularity_table(score)
        app.reveal(exercise())
    displayed = [float(value) for value in re.findall(r"popolarità: (\d+\.\d{3})", output.getvalue())]
    assert displayed == scores
    assert displayed == sorted(displayed)


def test_popularity_does_not_change_with_guess_results(tmp_path):
    app, output = app_for(tmp_path, ["kommen", "gehen", "gehen", "/q"], frequencies=popularity_table())
    app.run()
    assert output.getvalue().count("popolarità: 5.810") == 2
    assert [p.score for p in app.history.presentations] == [0, 1, None]
