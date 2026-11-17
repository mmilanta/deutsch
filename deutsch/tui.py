from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from rich.console import Console
from rich.text import Text

from deutsch.core import Deck, Exercise, append_guess

# Enable normal line editing on terminals that provide readline.
try:
    import readline  # noqa: F401
except ImportError:
    pass


def highlight(sentence: str, target: str) -> Text:
    before, _, after = sentence.partition(target)
    text = Text(before)
    text.append(target, style="bold cyan")
    text.append(after)
    return text


class DeutschApp:
    """An ordinary terminal conversation: no alternate screen or redraws."""

    def __init__(
        self,
        exercises: list[Exercise],
        log_path: Path,
        threshold: int = 1,
        *,
        console: Console | None = None,
        read_line: Callable[[], str] | None = None,
    ):
        self.deck = Deck(exercises)
        self.log_path = log_path
        self.threshold = threshold
        self.console = console if console is not None else Console()
        self.read_line = read_line
        self.session_id = str(uuid4())
        self.correct = 0
        self.guesses = 0

    def reveal(self, exercise: Exercise) -> None:
        self.console.print(highlight(exercise.german, exercise.german_target))
        if exercise.german_target != exercise.infinitive:
            self.console.print(Text(f"infinito: {exercise.infinitive}", style="dim"))
        if exercise.meaning is not None:
            self.console.print(Text(f"significato: {exercise.meaning}", style="dim"))
        self.console.print()
        self.console.rule(style="dim")
        self.console.print()

    def practice(self, exercise: Exercise) -> bool:
        self.console.print(highlight(exercise.italian, exercise.italian_target))
        attempt = 0
        while True:
            if self.read_line is None:
                # Readline must own the prompt to keep cursor movement and
                # deletion inside the editable answer, after the `> ` prefix.
                raw = input("> ")
            else:
                self.console.print("> ", style="dim", end="")
                raw = self.read_line()
            if raw.strip().lower() in {"/q", "/quit"}:
                return False
            if raw == "":
                self.reveal(exercise)
                return True
            try:
                result = append_guess(
                    self.log_path, exercise, raw, self.session_id, attempt + 1, self.threshold
                )
            except OSError as error:
                self.console.print(Text(f"Salvataggio non riuscito: {error}. Riprova.", style="red"))
                continue
            attempt += 1
            self.guesses += 1
            if result == "correct":
                self.correct += 1
                self.console.print("Corretto.", style="green")
                self.reveal(exercise)
                return True
            if result == "almost_there":
                self.console.print("Almost there — riprova.", style="yellow")
            else:
                self.console.print("Non ancora — riprova, o Invio per vedere la risposta.", style="red")

    def run(self) -> None:
        self.console.print("Deutsch · infinito tedesco · Invio: risposta · /q: esci", style="dim")
        self.console.print()
        try:
            while self.practice(self.deck.next()):
                pass
        except (EOFError, KeyboardInterrupt):
            self.console.print()
        self.console.print(Text(f"{self.correct} corrette · {self.guesses} tentativi", style="dim"))
