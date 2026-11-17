from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from rich.console import Console
from rich.text import Text

from deutsch.core import Deck, Exercise, append_guess
from deutsch.frequencies import FrequencyTable
from deutsch.history import History, Observation, append_event, events_path_for
from deutsch.scheduler import AdaptiveDeck
from deutsch.review import alternative_log_for, append_alternative_flag

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
        deck: Deck | AdaptiveDeck | None = None,
        history: History | None = None,
        events_path: Path | None = None,
        explain: bool = False,
        frequencies: FrequencyTable | None = None,
        alternative_log: Path | None = None,
    ):
        self.deck = deck if deck is not None else Deck(exercises)
        self.frequencies = frequencies
        if self.frequencies is None and isinstance(self.deck, AdaptiveDeck):
            self.frequencies = self.deck.frequencies
        self.history = self.deck.history if isinstance(self.deck, AdaptiveDeck) else history if history is not None else History()
        self.events_path = events_path if events_path is not None else events_path_for(log_path)
        self.explain = explain
        self.log_path = log_path
        self.alternative_log = alternative_log if alternative_log is not None else alternative_log_for(log_path)
        paths = [self.log_path, self.events_path, self.alternative_log]
        if len({path.resolve() for path in paths}) != len(paths):
            raise ValueError("Guess, presentation-event, and alternative-review logs must use different paths")
        self.previous_exercise: tuple[Exercise, str] | None = None
        self.flagged_presentations: set[str] = set()
        self.threshold = threshold
        self.console = console if console is not None else Console()
        self.read_line = read_line
        self.session_id = str(uuid4())
        self.correct = 0
        self.guesses = 0

    def reveal(self, exercise: Exercise) -> None:
        frequency = self.frequencies.for_word(exercise.word_id, exercise.infinitive) if self.frequencies is not None else None
        popularity = f"{frequency.zipf:.3f}" if frequency is not None and frequency.method != "missing" else "n/d"
        translation = highlight(exercise.german, exercise.german_target)
        translation.append(f"  · popolarità: {popularity}", style="dim")
        self.console.print(translation)
        if exercise.german_target != exercise.infinitive:
            self.console.print(Text(f"infinito: {exercise.infinitive}", style="dim"))
        if exercise.meaning is not None:
            self.console.print(Text(f"significato: {exercise.meaning}", style="dim"))
        self.console.rule(characters="-", style="dim")

    def flag_previous_alternative(self) -> None:
        if self.previous_exercise is None:
            self.console.print("Nessun esercizio precedente da segnalare.", style="blue")
            return
        exercise, presentation_id = self.previous_exercise
        if presentation_id in self.flagged_presentations:
            self.console.print("Esercizio precedente già segnalato.", style="blue")
            return
        try:
            append_alternative_flag(self.alternative_log, exercise, self.session_id, presentation_id)
        except OSError as error:
            self.console.print(Text(f"Segnalazione non riuscita: {error}. Riprova.", style="red"))
            return
        self.flagged_presentations.add(presentation_id)
        self.console.print("Esercizio precedente segnalato per revisione.", style="blue")

    def practice(self, exercise: Exercise) -> bool:
        presentation_id = str(uuid4())
        shown_at = datetime.now(timezone.utc)
        attempt = 0
        first_result = None
        finished = False
        try:
            append_event(self.events_path, exercise, self.session_id, presentation_id, "presented")
        except OSError as error:
            self.console.print(Text(f"Salvataggio non riuscito: {error}. Sessione interrotta.", style="red"))
            return False

        def finish(event: str) -> bool:
            nonlocal finished
            if finished:
                return True
            finished = True
            self.history.add(Observation(
                presentation_id, exercise.word_id, exercise.sentence_id, shown_at,
                meaning=exercise.meaning, expected_infinitive=exercise.infinitive,
                first_result=first_result, gave_up=event == "gave_up",
            ))
            try:
                append_event(self.events_path, exercise, self.session_id, presentation_id,
                             event, attempts=attempt, first_result=first_result)
            except OSError as error:
                self.console.print(Text(f"Evento non salvato: {error}. Sessione interrotta.", style="red"))
                return False
            if event in {"completed", "gave_up"}:
                self.previous_exercise = (exercise, presentation_id)
            return True

        if self.explain and isinstance(self.deck, AdaptiveDeck):
            # The reason contains learning evidence, never the answer/meaning.
            self.console.print(Text(self.deck.explain(exercise), style="dim"))
        self.console.print(highlight(exercise.italian, exercise.italian_target))
        try:
            while True:
                if self.read_line is None:
                    # Let readline protect the > prefix from cursor/backspace.
                    raw = input("> ")
                else:
                    self.console.print("> ", style="dim", end="")
                    raw = self.read_line()
                if raw.strip().lower() in {"/alternative", "/alt"}:
                    self.flag_previous_alternative()
                    continue
                if raw.strip().lower() in {"/q", "/quit"}:
                    finish("abandoned")
                    return False
                if raw == "":
                    saved = finish("gave_up")
                    self.reveal(exercise)
                    return saved
                try:
                    result = append_guess(
                        self.log_path, exercise, raw, self.session_id, attempt + 1, self.threshold,
                        presentation_id=presentation_id,
                    )
                except OSError as error:
                    self.console.print(Text(f"Salvataggio non riuscito: {error}. Riprova.", style="red"))
                    continue
                attempt += 1
                self.guesses += 1
                if first_result is None:
                    first_result = result
                if result == "correct":
                    saved = finish("completed")
                    self.correct += 1
                    self.console.print("Corretto.", style="green")
                    self.reveal(exercise)
                    return saved
                if result == "almost_there":
                    self.console.print("Almost there — riprova.", style="yellow")
                else:
                    self.console.print("Non ancora — riprova, o Invio per vedere la risposta.", style="red")
        except (EOFError, KeyboardInterrupt):
            finish("abandoned")
            raise

    def run(self) -> None:
        mode = " · adattivo" if isinstance(self.deck, AdaptiveDeck) else ""
        self.console.print(f"Deutsch{mode} · infinito tedesco · Invio: risposta · /q: esci · /alt: segnala precedente", style="dim")
        self.console.print()
        try:
            while self.practice(self.deck.next()):
                pass
        except (EOFError, KeyboardInterrupt):
            self.console.print()
        self.console.print(Text(f"{self.correct} corrette · {self.guesses} tentativi", style="dim"))
