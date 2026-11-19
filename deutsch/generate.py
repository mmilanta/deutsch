from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from deutsch.core import Exercise, load_exercises
from deutsch.vocabulary import audit_vocabulary, load_vocabulary

SOURCE = "https://gist.githubusercontent.com/wanderingstan/7eaaf0e22461b505c749e268c0b72bc4/raw/top-german-verbs.csv"
MODEL = "gpt-6-luna"


class Batch(BaseModel):
    exercises: list[Exercise]


def generate(output: Path, count: int, batch_size: int = 10, *, vocabulary: Path = Path("data/vocabulary.json")) -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY in .env or the environment.")
    entries = load_vocabulary(vocabulary)
    if not 1 <= count <= len(entries) or batch_size < 1:
        raise ValueError(f"Count must be between 1 and {len(entries)}, and batch size must be positive.")
    selected = entries[:count]
    existing = load_exercises(output, allow_empty=True) if output.exists() else []
    errors = audit_vocabulary(entries, existing).errors
    if errors:
        raise ValueError("; ".join(errors))
    by_id = {item.sentence_id: item for item in existing}
    existing_words = {item.word_id for item in existing}
    missing = [entry for entry in selected if entry.word_id not in existing_words]
    pending = [entry for entry in missing if entry.review_note is None]
    blocked = len(missing) - len(pending)
    print(f"Model: {MODEL} · {len(pending)} new exercises · {len(existing)} cached · {blocked} need lexical review", flush=True)
    client = OpenAI(timeout=180, max_retries=2)
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        words = [{"word_id": entry.word_id, "infinitive": entry.infinitive,
                  **({"meaning": entry.meanings[0]} if entry.meanings else {})} for entry in batch]
        print(f"Generating {start + 1}–{start + len(batch)} of {len(pending)}…", flush=True)
        response = client.responses.parse(
            model=MODEL,
            input=[
                {"role": "system", "content": (
                    "Create accurate Italian-to-German vocabulary exercises for Italian-speaking learners. "
                    "Use standard German spelling, retaining ß where appropriate (heißen, weiß, Straße). "
                    "For EACH supplied German infinitive, produce exactly one natural short Italian sentence "
                    "and its faithful German translation, preferably A1/A2 (use a harder sentence only if the verb requires it). "
                    "Use the supplied word_id and infinitive unchanged; sentence_id must be word_id + '-01'. "
                    "If a meaning label is supplied, illustrate that sense and copy it exactly into meaning; otherwise set meaning to null. "
                    "italian_target is the exact verb or contiguous verb phrase in the Italian sentence corresponding "
                    "to the target German verb; german_target is the exact inflected verb in the German sentence. "
                    "Each target must occur EXACTLY ONCE, with matching case. No markdown. "
                    "For separable verbs prefer a modal construction so the target infinitive is contiguous. "
                    "Avoid ambiguous translations where possible. The learner always answers with the German infinitive. "
                    "Set accepted_infinitives to null; alternatives are curated separately. "
                    "The source includes rare verbs such as 'einen': respect their actual meaning, do not silently replace them."
                )},
                {"role": "user", "content": json.dumps(words, ensure_ascii=False)},
            ],
            text_format=Batch,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("The model returned no exercises; existing batches are saved.")
        expected = {item["word_id"]: item["infinitive"] for item in words}
        if len(parsed.exercises) != len(expected) or {item.word_id for item in parsed.exercises} != set(expected):
            raise ValueError("The model returned missing, duplicate, or unexpected verbs; batch was not saved.")
        for item in parsed.exercises:
            if item.infinitive != expected[item.word_id] or item.sentence_id != item.word_id + "-01":
                raise ValueError("The model changed an infinitive or sentence ID; batch was not saved.")
        errors = audit_vocabulary(entries, parsed.exercises).errors
        requested_meanings = {word["word_id"]: word.get("meaning") for word in words}
        for item in parsed.exercises:
            if item.meaning != requested_meanings[item.word_id]:
                errors.append(f"The model changed the meaning label for {item.word_id}")
            if item.accepted_infinitives is not None:
                errors.append(f"The model supplied unreviewed alternatives for {item.sentence_id}")
        if errors:
            raise ValueError("; ".join(errors))
        by_id.update({item.sentence_id: item for item in parsed.exercises})
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps([item.model_dump(exclude_none=True) for item in by_id.values()], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
        print(f"Saved {len(by_id)} exercises to {output}", flush=True)
