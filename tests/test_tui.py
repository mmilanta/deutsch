import io
import json

from rich.console import Console

from deutsch.core import Exercise
from deutsch.tui import DeutschApp, highlight


def sample():
    return Exercise(word_id="verb-8", sentence_id="verb-8-01", infinitive="gehen",
                    italian="Io vado a casa.", italian_target="vado",
                    german="Ich gehe nach Hause.", german_target="gehe")


def run_app(tmp_path, answers, *, log_path=None):
    output = io.StringIO()
    lines = iter(answers)
    app = DeutschApp([sample()], log_path if log_path is not None else tmp_path / "guesses.jsonl",
                     console=Console(file=output, color_system=None, width=80),
                     read_line=lambda: next(lines))
    app.run()
    return app, output.getvalue()


def test_guess_reveal_and_logging(tmp_path):
    app, output = run_app(tmp_path, ["  gehn  ", " GEHEN ", "/q"])
    assert "Almost there" in output
    assert "Corretto." in output
    assert "Ich gehe nach Hause." in output
    assert "infinito: gehen" in output
    assert app.correct == 1
    assert app.guesses == 2
    assert output.count("Io vado a casa.") == 2  # Previous prompt stays in scrollback.
    assert f"infinito: gehen\n{'-' * 80}\nIo vado a casa." in output
    records = [json.loads(line) for line in (tmp_path / "guesses.jsonl").read_text().splitlines()]
    assert [record["result"] for record in records] == ["almost_there", "correct"]
    assert records[0]["guess"] == "  gehn  "
    assert records[1]["guess"] == " GEHEN "
    assert records[1]["attempt"] == 2
    assert "\x1b[" not in output  # No colors or screen controls in plain output.


def test_reveal_and_quit_are_not_guesses(tmp_path):
    app, output = run_app(tmp_path, ["", "/q"])
    assert "Ich gehe nach Hause." in output
    separator = "-" * 80
    assert f"infinito: gehen\n{separator}\nIo vado a casa." in output
    assert app.guesses == 0
    assert not (tmp_path / "guesses.jsonl").exists()


def test_wrong_and_whitespace_guesses(tmp_path):
    app, output = run_app(tmp_path, ["kommen", "  ", "", "/q"])
    records = [json.loads(line) for line in (tmp_path / "guesses.jsonl").read_text().splitlines()]
    assert app.guesses == 2
    assert records[1]["guess"] == "  "
    assert records[1]["result"] == "incorrect"
    assert "Non ancora" in output


def test_failed_logging(tmp_path):
    app, output = run_app(tmp_path, ["gehen", "/q"], log_path=tmp_path)
    assert app.guesses == 0
    assert app.correct == 0
    assert "Salvataggio non riuscito" in output
    assert "Corretto." not in output


def test_eof_and_interrupt_exit_cleanly(tmp_path):
    for exception in (EOFError, KeyboardInterrupt):
        output = io.StringIO()

        def stop():
            raise exception

        app = DeutschApp([sample()], tmp_path / "guesses.jsonl",
                         console=Console(file=output, color_system=None), read_line=stop)
        app.run()
        assert "0 corrette" in output.getvalue()


def test_readline_owns_the_prompt(tmp_path, monkeypatch):
    output = io.StringIO()
    prompts = []

    def read_answer(prompt):
        prompts.append(prompt)
        return "/q"

    monkeypatch.setattr("builtins.input", read_answer)
    app = DeutschApp([sample()], tmp_path / "guesses.jsonl",
                     console=Console(file=output, color_system=None))
    app.run()
    assert prompts == ["> "]
    assert "> " not in output.getvalue()  # Not printed separately from readline.


def test_meaning_only_shown_after_reveal(tmp_path):
    output = io.StringIO()
    exercise = sample().model_copy(update={"meaning": "spostarsi a piedi (test)"})
    app = DeutschApp([exercise], tmp_path / "guesses.jsonl",
                     console=Console(file=output, color_system=None), read_line=lambda: "/q")
    assert app.practice(exercise) is False
    assert "spostarsi a piedi" not in output.getvalue()
    app.reveal(exercise)
    assert "significato: spostarsi a piedi (test)" in output.getvalue()


def test_target_is_bold():
    text = highlight("Ich gehe nach Hause.", "gehe")
    assert text.plain == "Ich gehe nach Hause."
    assert str(text.spans[0].style) == "bold cyan"
