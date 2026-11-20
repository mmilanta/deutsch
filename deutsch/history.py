"""Append-only presentation events and conservative reconstruction of old guesses."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from deutsch.core import Exercise, normalize

RESULTS = {"correct", "almost_there", "incorrect"}
EVENTS = {"presented", "completed", "gave_up", "abandoned"}


def events_path_for(guesses: Path) -> Path:
    return guesses.with_name(guesses.stem + ".events.jsonl")


def append_event(path: Path, exercise: Exercise, session_id: str, presentation_id: str,
                 event: str, *, attempts: int = 0, first_result: str | None = None) -> None:
    if event not in EVENTS:
        raise ValueError(f"Unknown presentation event: {event}")
    record = {
        "schema_version": 1, "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id, "presentation_id": presentation_id,
        "word_id": exercise.word_id, "sentence_id": exercise.sentence_id,
        "expected_infinitive": exercise.infinitive, "attempts": attempts,
    }
    if first_result is not None:
        record["first_result"] = first_result
    if exercise.meaning is not None:
        record["meaning"] = exercise.meaning
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


@dataclass
class Observation:
    presentation_id: str
    word_id: str
    sentence_id: str
    timestamp: datetime
    meaning: str | None = None
    expected_infinitive: str | None = None
    first_result: str | None = None
    gave_up: bool = False
    legacy: bool = False
    completed: bool = False
    attempts: int = 0
    correct_attempts: int = 0

    @property
    def score(self) -> float | None:
        if self.gave_up:
            return 0.0
        return {"correct": 1.0, "almost_there": 0.5, "incorrect": 0.0}.get(self.first_result)


@dataclass
class History:
    presentations: list[Observation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _by_word: dict[str, list[Observation]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_word = {}
        for item in self.presentations:
            self._by_word.setdefault(item.word_id, []).append(item)

    def add(self, item: Observation) -> None:
        self.presentations.append(item)
        self._by_word.setdefault(item.word_id, []).append(item)

    def for_word(self, word_id: str, infinitive: str) -> list[Observation]:
        return [p for p in self._by_word.get(word_id, []) if
                (p.expected_infinitive is None or normalize(p.expected_infinitive) == normalize(infinitive))]


def _records(path: Path, warnings: list[str]):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("record is not an object")
                yield number, record
            except (ValueError, TypeError) as error:
                warnings.append(f"{path}:{number}: ignored invalid record ({error})")


def load_history(guesses: Path, events: Path | None = None) -> History:
    """Never rewrite old data; no reveal is inferred from a missing old event."""
    history = History()
    groups: dict[str, Observation] = {}
    neutral_prefixes: dict[str, int] = {}
    previous_legacy_key = None
    previous_attempt = 0
    legacy_id = ""

    def get_group(record: dict, identifier: str, timestamp: datetime, *, legacy: bool = False) -> Observation:
        word_id, sentence_id = record["word_id"], record["sentence_id"]
        if not isinstance(word_id, str) or not isinstance(sentence_id, str):
            raise ValueError("word_id and sentence_id must be strings")
        meaning = record.get("meaning")
        expected = record.get("expected_infinitive")
        if meaning is not None and not isinstance(meaning, str):
            raise ValueError("meaning must be a string")
        if expected is not None and not isinstance(expected, str):
            raise ValueError("expected_infinitive must be a string")
        if identifier not in groups:
            groups[identifier] = Observation(identifier, word_id, sentence_id, timestamp, meaning, expected, legacy=legacy)
        group = groups[identifier]
        if group.word_id != word_id or group.sentence_id != sentence_id or group.meaning != meaning:
            raise ValueError("conflicting metadata for presentation ID")
        if group.expected_infinitive and expected and normalize(group.expected_infinitive) != normalize(expected):
            raise ValueError("conflicting expected answer for presentation ID")
        if timestamp < group.timestamp:
            group.timestamp = timestamp
        return group

    for number, record in _records(guesses, history.warnings):
        try:
            if record.get("schema_version", 1) not in {1, 2}:
                raise ValueError("unsupported guess schema")
            result = record.get("result")
            if result not in RESULTS and result != "valid_alternative":
                raise ValueError("unknown guess result")
            timestamp = parse_time(record["timestamp"])
            attempt = record.get("attempt", 1)
            if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
                raise ValueError("invalid attempt number")
            identifier = record.get("presentation_id")
            legacy = identifier is None
            if legacy:
                key = (record.get("session_id"), record["word_id"], record["sentence_id"])
                if key != previous_legacy_key or attempt <= previous_attempt:
                    legacy_id = f"legacy-line-{number}"
                identifier = legacy_id
                previous_legacy_key, previous_attempt = key, attempt
            else:
                previous_legacy_key, previous_attempt = None, 0
                if not isinstance(identifier, str) or not identifier:
                    raise ValueError("invalid presentation ID")
            group = get_group(record, identifier, timestamp, legacy=legacy)
            next_scored_attempt = neutral_prefixes.get(identifier, 0) + 1
            if result == "valid_alternative":
                if attempt == next_scored_attempt:
                    neutral_prefixes[identifier] = attempt
                continue
            group.attempts += 1
            group.correct_attempts += result == "correct"
            # A later success is not first-attempt recall unless the preceding
            # submissions are present and were all recognized alternatives.
            if attempt == next_scored_attempt and group.first_result is None:
                group.first_result = result
            if result == "correct":
                group.completed = True
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            history.warnings.append(f"{guesses}:{number}: ignored invalid guess ({error})")

    terminated: set[str] = set()
    for number, record in _records(events if events is not None else events_path_for(guesses), history.warnings):
        try:
            if record.get("schema_version", 1) != 1:
                raise ValueError("unsupported event schema")
            event = record["event"]
            if event not in EVENTS:
                raise ValueError("unknown presentation event")
            identifier = record["presentation_id"]
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("invalid presentation ID")
            first = record.get("first_result")
            if first is not None and first not in RESULTS:
                raise ValueError("unknown first result")
            group = get_group(record, identifier, parse_time(record["timestamp"]))
            if event != "presented":
                if identifier in terminated:
                    raise ValueError("duplicate terminal event")
                terminated.add(identifier)
                group.gave_up = event == "gave_up"
                group.completed = event == "completed"
                attempts = record.get("attempts", 0)
                if type(attempts) is int and attempts >= 0:
                    group.attempts = max(group.attempts, attempts)
                if group.completed:
                    group.correct_attempts = max(group.correct_attempts, 1)
                if group.first_result is None:
                    group.first_result = first
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            history.warnings.append(f"{events or events_path_for(guesses)}:{number}: ignored invalid event ({error})")
    return History(presentations=sorted(groups.values(), key=lambda p: p.timestamp), warnings=history.warnings)
