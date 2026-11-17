from __future__ import annotations

import json
import random
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator


def swiss_spelling(text: str) -> str:
    return text.replace("ß", "ss").replace("ẞ", "SS")


class Exercise(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word_id: str
    sentence_id: str
    infinitive: str = Field(min_length=1)
    italian: str
    italian_target: str = Field(min_length=1)
    german: str
    german_target: str = Field(min_length=1)
    meaning: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_targets(self) -> Exercise:
        for sentence, target in [(self.italian, self.italian_target), (self.german, self.german_target)]:
            if sentence.count(target) != 1:
                raise ValueError(f"Target {target!r} must occur exactly once in {sentence!r}")
        return self


def normalize(text: str) -> str:
    return swiss_spelling(unicodedata.normalize("NFC", text.strip().lower()))


def levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def evaluate(guess: str, expected: str, threshold: int = 1) -> tuple[str, int]:
    distance = levenshtein(normalize(guess), normalize(expected))
    result = "correct" if distance == 0 else "almost_there" if distance <= threshold else "incorrect"
    return result, distance


def load_exercises(path: Path, *, allow_empty: bool = False) -> list[Exercise]:
    exercises = [Exercise.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    if not exercises and not allow_empty:
        raise ValueError("The exercise file is empty. Add sentence pairs for the vocabulary first.")
    ids = [exercise.sentence_id for exercise in exercises]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate sentence IDs in exercise file")
    infinitives: dict[str, str] = {}
    for exercise in exercises:
        if exercise.word_id in infinitives and infinitives[exercise.word_id] != exercise.infinitive:
            raise ValueError(f"Conflicting infinitives for word ID {exercise.word_id}")
        infinitives[exercise.word_id] = exercise.infinitive
    return exercises


def append_guess(path: Path, exercise: Exercise, guess: str, session_id: str, attempt: int, threshold: int = 1,
                 *, presentation_id: str | None = None) -> str:
    result, distance = evaluate(guess, exercise.infinitive, threshold)
    record = {
        "schema_version": 2 if presentation_id is not None else 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "word_id": exercise.word_id,
        "sentence_id": exercise.sentence_id,
        "expected_infinitive": exercise.infinitive,
        "guess": guess,
        "result": result,
        "levenshtein_distance": distance,
        "threshold": threshold,
        "attempt": attempt,
    }
    if presentation_id is not None:
        record["presentation_id"] = presentation_id
    if exercise.meaning is not None:
        record["meaning"] = exercise.meaning
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return result


class Deck:
    """One visit per word per round; rotate through that word's sentence variants."""

    def __init__(self, exercises: list[Exercise]):
        if not exercises:
            raise ValueError("The deck must contain at least one exercise")
        self.by_word: dict[str, list[Exercise]] = {}
        for exercise in exercises:
            self.by_word.setdefault(exercise.word_id, []).append(exercise)
        self.queue: list[str] = []
        self.variant_queues: dict[str, list[Exercise]] = {}
        self.last_variant: dict[str, Exercise] = {}
        self.last: Exercise | None = None

    def next(self) -> Exercise:
        if not self.queue:
            self.queue = random.sample(list(self.by_word), len(self.by_word))
            if len(self.queue) > 1 and self.last is not None and self.last.word_id == self.queue[-1]:
                self.queue[0], self.queue[-1] = self.queue[-1], self.queue[0]
        word_id = self.queue.pop()
        variants = self.variant_queues.setdefault(word_id, [])
        if not variants:
            variants.extend(random.sample(self.by_word[word_id], len(self.by_word[word_id])))
            if len(variants) > 1 and self.last_variant.get(word_id) == variants[-1]:
                variants[0], variants[-1] = variants[-1], variants[0]
        self.last = variants.pop()
        self.last_variant[word_id] = self.last
        return self.last
