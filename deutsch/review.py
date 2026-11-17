"""Private, append-only requests to review possible sentence ambiguities."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from deutsch.core import Exercise


def alternative_log_for(guess_log: Path) -> Path:
    return guess_log.with_name(guess_log.stem + ".alternatives.jsonl")


def append_alternative_flag(path: Path, exercise: Exercise, session_id: str,
                            presentation_id: str) -> None:
    # Store the previous prompt's context and stable history link, not the
    # current prompt or any invented alternative. Actual guesses remain in
    # the separate private guess log, linked by presentation_id.
    record = {
        "schema_version": 1,
        "event": "alternative_requested",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "presentation_id": presentation_id,
        "word_id": exercise.word_id,
        "sentence_id": exercise.sentence_id,
        "expected_infinitive": exercise.infinitive,
        "italian": exercise.italian,
        "italian_target": exercise.italian_target,
        "german": exercise.german,
        "german_target": exercise.german_target,
    }
    if exercise.meaning is not None:
        record["meaning"] = exercise.meaning
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
