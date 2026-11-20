from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from rich.console import Console
from rich.text import Text

from deutsch.core import Exercise, append_guess
from deutsch.difficulty import GameOptions, ordered_exercises
from deutsch.history import History, Observation, append_event, events_path_for
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
        difficulty: dict[str, float] | None = None,
        options: GameOptions = GameOptions(),
        seed: int | None = None,
        events_path: Path | None = None,
        alternative_log: Path | None = None,
    ):
        self.difficulty = difficulty or {}
        self.deck = ordered_exercises(exercises, self.difficulty, options, seed)
        self.lives_left = options.lives
        self.history = History()
        self.events_path = events_path if events_path is not None else events_path_for(log_path)
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
        score = self.difficulty.get(exercise.sentence_id)
        difficulty = f"{score:.3f}" if score is not None else "n/d"
        translation = highlight(exercise.german, exercise.german_target)
        translation.append(f"  · difficoltà: {difficulty}", style="dim")
        self.console.print(translation)
        if exercise.german_target != exercise.infinitive:
            self.console.print(Text(f"infinito: {exercise.infinitive}", style="dim"))
        if exercise.meaning is not None:
            self.console.print(Text(f"significato: {exercise.meaning}", style="dim"))
        if exercise.accepted_infinitives:
            self.console.print(Text(f"altre traduzioni valide: {', '.join(exercise.accepted_infinitives)}", style="dim"))
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
        attempt = scored_attempts = 0
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
                             event, attempts=scored_attempts, first_result=first_result)
            except OSError as error:
                self.console.print(Text(f"Evento non salvato: {error}. Sessione interrotta.", style="red"))
                return False
            if event in {"completed", "gave_up"}:
                self.previous_exercise = (exercise, presentation_id)
            return True

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
                    self.lives_left -= 1
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
                if result == "valid_alternative":
                    self.console.print("Traduzione valida, ma cerchiamo un altro verbo.", style="blue")
                    continue
                scored_attempts += 1
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
        self.console.print("Deutsch · infinito tedesco · Invio vuoto: salta · /q: esci · /alt: segnala precedente", style="dim")
        self.console.print()
        try:
            for number, exercise in enumerate(self.deck, 1):
                self.console.print(f"{number}/{len(self.deck)} · vite rimaste: {self.lives_left}", style="dim")
                if not self.practice(exercise):
                    break
                if not self.lives_left:
                    self.console.print("Vite esaurite.")
                    break
            else:
                self.console.print("Partita completata.")
        except (EOFError, KeyboardInterrupt):
            self.console.print()
        self.console.print(Text(f"{self.correct} corrette · {self.guesses} tentativi", style="dim"))
