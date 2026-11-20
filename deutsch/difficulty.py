"""Offline sentence ordering for the lives-based game."""
from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path

from deutsch.core import Exercise

DEFAULT_DIFFICULTY = Path("data/difficulty/ranking.tsv")
MAX_LIVES = 2**53 - 1


@dataclass(frozen=True)
class GameOptions:
    lives: int = 3
    randomness: float = 0.0

    def __post_init__(self):
        if type(self.lives) is not int or not 1 <= self.lives <= MAX_LIVES:
            raise ValueError("Le vite devono essere un numero intero positivo.")
        if type(self.randomness) not in (int, float) or not 0 <= self.randomness <= 2:
            raise ValueError("La casualità deve essere tra 0 e 2.")


def load_difficulty(path: Path, exercises: list[Exercise]) -> dict[str, float]:
    by_id = {exercise.sentence_id: exercise for exercise in exercises}
    scores: dict[str, float] = {}
    seen = set()
    with path.open(encoding="utf-8", newline="") as source:
        rows = csv.DictReader(source, delimiter="\t")
        if not {"sentence_id", "difficulty", "infinitive", "meaning", "italian"} <= set(rows.fieldnames or ()):
            raise ValueError(f"{path}: invalid difficulty columns")
        for number, row in enumerate(rows, 2):
            sid = row["sentence_id"]
            try:
                score = float(row["difficulty"])
                if not sid or sid in seen or not math.isfinite(score):
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}:{number}: invalid or duplicate difficulty entry") from error
            seen.add(sid)
            exercise = by_id.get(sid)
            if exercise and (exercise.infinitive, exercise.meaning or "", exercise.italian) == (
                    row["infinitive"], row["meaning"], row["italian"]):
                scores[sid] = score
    return scores


def ordered_exercises(exercises: list[Exercise], difficulty: dict[str, float], options: GameOptions,
                      seed: int | None = None) -> list[Exercise]:
    """Easier known sentences first, then unranked sentences in input order."""
    rng = random.Random(seed)

    def priority(exercise: Exercise):
        score = difficulty.get(exercise.sentence_id)
        if score is None:
            return 1, 0.0
        if options.randomness:
            # Independent Gumbel noise favors smaller difficulty differences.
            score += options.randomness * math.log(-math.log(max(rng.random(), 2**-53)))
        return 0, score

    return sorted(exercises, key=priority)
