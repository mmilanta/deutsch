"""Import directly authored sentence pairs without making API calls."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from deutsch.core import Exercise, load_exercises
from deutsch.vocabulary import VocabularyEntry, audit_vocabulary, load_vocabulary


def unmark(text: str) -> tuple[str, str]:
    parts = text.split("**")
    if len(parts) != 3 or not parts[1]:
        raise ValueError("Each sentence must contain exactly one **highlighted target**")
    before, target, after = parts
    return before + target + after, target


def import_authored(sources: list[Path], vocabulary: Path, output: Path) -> int:
    if vocabulary.suffix.lower() == ".csv":  # Compatibility with the original source snapshot.
        with vocabulary.open(encoding="utf-8-sig", newline="") as file:
            entries = [VocabularyEntry(word_id=f"verb-{row['Rank']}", infinitive=row["Infinitiv"])
                       for row in csv.DictReader(file)]
    else:
        entries = load_vocabulary(vocabulary)
    infinitives = {entry.word_id: entry.infinitive for entry in entries}
    existing = load_exercises(output, allow_empty=True) if output.exists() else []
    errors = audit_vocabulary(entries, existing).errors
    if errors:
        raise ValueError("; ".join(errors))
    by_id = {item.sentence_id: item for item in existing}
    word_infinitives = {item.word_id: item.infinitive for item in existing}
    added = 0
    for source in sources:
        with source.open(encoding="utf-8", newline="") as file:
            for line, row in enumerate(csv.DictReader(file, delimiter="\t"), 2):
                try:
                    rank = row.get("rank")
                    word_id = row.get("word_id") or (f"verb-{rank}" if rank else None)
                    if not word_id:
                        raise ValueError("Each row needs a word_id (or a legacy rank)")
                    if rank and word_id != f"verb-{rank}":
                        raise ValueError("Conflicting word_id and legacy rank")
                    if word_id not in infinitives:
                        raise ValueError(f"Unknown word ID: {word_id}; add it to the vocabulary list first")
                    italian_text, german_text = row["italian"], row["german"]
                    frame = row.get("frame") or "full"
                    frames = {
                        "full": ("", ""),
                        "can": ("Si può ", "Man kann "),
                        "want": ("Voglio ", "Ich möchte "),
                        "need": ("Devo ", "Ich muss "),
                    }
                    italian_prefix, german_prefix = frames[frame]
                    suffix = "" if frame == "full" else "."
                    italian, italian_target = unmark(italian_prefix + italian_text + suffix)
                    german, german_target = unmark(german_prefix + german_text + suffix)
                    item = Exercise(
                        word_id=word_id,
                        sentence_id=row.get("sentence_id") or f"{word_id}-01",
                        infinitive=infinitives[word_id], italian=italian, italian_target=italian_target,
                        german=german, german_target=german_target,
                        meaning=row.get("meaning") or None,
                    )
                    if item.word_id in word_infinitives and word_infinitives[item.word_id] != item.infinitive:
                        raise ValueError(f"Conflicting infinitives for word ID {item.word_id}")
                    if item.sentence_id in by_id:
                        if item != by_id[item.sentence_id]:
                            raise ValueError(f"Refusing to replace an existing exercise: {item.sentence_id}")
                        continue
                    by_id[item.sentence_id] = item
                    word_infinitives[item.word_id] = item.infinitive
                    added += 1
                except (KeyError, ValueError, TypeError) as error:
                    raise ValueError(f"{source}:{line}: {error}") from error
    errors = audit_vocabulary(entries, list(by_id.values())).errors
    if errors:
        raise ValueError("; ".join(errors))
    if not added:
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    order = {entry.word_id: index for index, entry in enumerate(entries)}
    ordered = sorted(by_id.values(), key=lambda item: (order[item.word_id], item.sentence_id))
    temporary.write_text(json.dumps([item.model_dump(exclude_none=True) for item in ordered], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return added
