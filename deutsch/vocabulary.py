"""The canonical vocabulary list and deterministic, offline coverage checks."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deutsch.core import Exercise, load_exercises


class VocabularyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    infinitive: str = Field(min_length=1)
    meanings: list[str] = Field(default_factory=list)
    review_note: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_entry(self) -> VocabularyEntry:
        if not self.infinitive.strip() or self.infinitive != self.infinitive.strip():
            raise ValueError("The infinitive must be nonempty and have no surrounding whitespace")
        if any(not meaning.strip() or meaning != meaning.strip() for meaning in self.meanings):
            raise ValueError("Meanings must be nonempty and have no surrounding whitespace")
        if len(set(self.meanings)) != len(self.meanings):
            raise ValueError("Duplicate meanings in vocabulary entry")
        return self


def load_vocabulary(path: Path) -> list[VocabularyEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Vocabulary must be a JSON list")
    entries = [VocabularyEntry.model_validate(item) for item in data]
    ids = [entry.word_id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate word IDs in vocabulary list")
    return entries


class MissingMeaning(BaseModel):
    word_id: str
    infinitive: str
    meaning: str


class CoverageReport(BaseModel):
    vocabulary_count: int
    sentence_count: int
    covered_word_count: int
    missing_words: list[VocabularyEntry]
    missing_meanings: list[MissingMeaning]
    errors: list[str]

    @property
    def complete(self) -> bool:
        return not self.missing_words and not self.missing_meanings and not self.errors


def audit_vocabulary(entries: list[VocabularyEntry], exercises: list[Exercise]) -> CoverageReport:
    by_id = {entry.word_id: entry for entry in entries}
    if len(by_id) != len(entries):
        raise ValueError("Duplicate word IDs in vocabulary list")
    by_word: dict[str, list[Exercise]] = {}
    errors: list[str] = []
    seen: set[str] = set()
    for exercise in exercises:
        if exercise.sentence_id in seen:
            errors.append(f"Duplicate sentence ID: {exercise.sentence_id}")
            continue
        seen.add(exercise.sentence_id)
        entry = by_id.get(exercise.word_id)
        if entry is None:
            errors.append(f"Unknown word ID {exercise.word_id} in sentence {exercise.sentence_id}")
            continue
        if exercise.infinitive != entry.infinitive:
            errors.append(f"Infinitive mismatch for sentence {exercise.sentence_id}: expected {entry.infinitive!r}")
            continue
        if entry.meanings and exercise.meaning is not None and exercise.meaning not in entry.meanings:
            errors.append(f"Undeclared meaning {exercise.meaning!r} in sentence {exercise.sentence_id}")
            continue
        by_word.setdefault(exercise.word_id, []).append(exercise)
    missing_words = [entry for entry in entries if not by_word.get(entry.word_id)]
    missing_meanings = []
    for entry in entries:
        available = {exercise.meaning for exercise in by_word.get(entry.word_id, [])}
        missing_meanings.extend(
            MissingMeaning(word_id=entry.word_id, infinitive=entry.infinitive, meaning=meaning)
            for meaning in entry.meanings if meaning not in available
        )
    return CoverageReport(
        vocabulary_count=len(entries), sentence_count=len(exercises), covered_word_count=len(by_word),
        missing_words=missing_words, missing_meanings=missing_meanings, errors=errors,
    )


def check_vocabulary(vocabulary: Path, exercises: Path) -> CoverageReport:
    entries = load_vocabulary(vocabulary)
    sentences = load_exercises(exercises, allow_empty=True) if exercises.exists() else []
    return audit_vocabulary(entries, sentences)
