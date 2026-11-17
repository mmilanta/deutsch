import json

import pytest
from pydantic import ValidationError

from deutsch.core import Deck, Exercise, append_guess, evaluate, levenshtein, load_exercises


@pytest.fixture
def exercise():
    return Exercise(word_id="verb-8", sentence_id="verb-8-01", infinitive="gehen",
                    italian="Io vado a casa.", italian_target="vado",
                    german="Ich gehe nach Hause.", german_target="gehe")


@pytest.mark.parametrize("guess, expected, result, distance", [
    ("  GeHeN  ", "gehen", "correct", 0),
    ("gehn", "gehen", "almost_there", 1),
    ("geheen", "gehen", "almost_there", 1),
    ("gehan", "gehen", "almost_there", 1),
    ("gehe", "gehen", "almost_there", 1),
    ("kommen", "gehen", "incorrect", 4),
    ("", "gehen", "incorrect", 5),
    ("ko\u0308nnen", "können", "correct", 0),
    ("heissen", "heißen", "correct", 0),
    ("heißen", "heissen", "correct", 0),
    ("  HEIẞEN  ", "heissen", "correct", 0),
])
def test_evaluate(guess, expected, result, distance):
    assert evaluate(guess, expected) == (result, distance)


def test_distance_and_threshold():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "") == 0
    assert evaluate("gehn", "gehen", threshold=0)[0] == "incorrect"


def test_log_preserves_raw_input(tmp_path, exercise):
    path = tmp_path / "nested" / "guesses.jsonl"
    assert append_guess(path, exercise, "  GEHN  ", "session", 1) == "almost_there"
    assert append_guess(path, exercise, "gehen", "session", 2) == "correct"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["guess"] == "  GEHN  "
    assert records[0]["expected_infinitive"] == "gehen"
    assert records[0]["levenshtein_distance"] == 1
    assert records[1]["attempt"] == 2
    assert records[0]["timestamp"].endswith("+00:00")


def test_validation(exercise):
    with pytest.raises(ValidationError):
        Exercise(**(exercise.model_dump() | {"german_target": "gehen"}))


def test_eszett_display_and_swiss_guess(tmp_path):
    exercise = Exercise(word_id="heissen", sentence_id="heissen-01", infinitive="heißen",
                        italian="Mi chiamo Marco.", italian_target="Mi chiamo",
                        german="Ich heiße Marco.", german_target="heiße")
    assert exercise.infinitive == "heißen"
    assert exercise.german == "Ich heiße Marco."
    assert exercise.german_target == "heiße"
    path = tmp_path / "guesses.jsonl"
    for attempt, guess in enumerate(["heissen", "heißen"], 1):
        assert append_guess(path, exercise, guess, "session", attempt) == "correct"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["guess"] for r in records] == ["heissen", "heißen"]
    assert all(r["expected_infinitive"] == "heißen" for r in records)
    assert all(r["levenshtein_distance"] == 0 for r in records)


def test_multiple_sentences_load_and_validate(tmp_path, exercise):
    second = exercise.model_copy(update={"sentence_id": "verb-8-02", "meaning": "secondo uso (test)"})
    path = tmp_path / "exercises.json"
    path.write_text(json.dumps([exercise.model_dump(exclude_none=True), second.model_dump()]))
    loaded = load_exercises(path)
    assert loaded[0].meaning is None  # Legacy records need no migration.
    assert loaded[1].meaning == "secondo uso (test)"
    assert loaded[0].word_id == loaded[1].word_id
    path.write_text(json.dumps([exercise.model_dump(), exercise.model_dump()]))
    with pytest.raises(ValueError, match="Duplicate sentence IDs"):
        load_exercises(path)
    conflicting = second.model_copy(update={"infinitive": "kommen"})
    path.write_text(json.dumps([exercise.model_dump(), conflicting.model_dump()]))
    with pytest.raises(ValueError, match="Conflicting infinitives"):
        load_exercises(path)


def test_deck_balances_words_and_rotates_variants(exercise):
    variants = [exercise.model_copy(update={"sentence_id": f"verb-8-{i:02}"}) for i in range(1, 4)]
    other = exercise.model_copy(update={"word_id": "other", "sentence_id": "other-01"})
    deck = Deck(variants + [other])
    previous = None
    per_word = []
    for _ in range(12):
        round_ = [deck.next(), deck.next()]
        assert {e.word_id for e in round_} == {exercise.word_id, other.word_id}
        if previous is not None:
            assert previous.word_id != round_[0].word_id
        previous = round_[-1]
        per_word.extend(e.sentence_id for e in round_ if e.word_id == exercise.word_id)
    for start in range(0, len(per_word), 3):
        assert len(set(per_word[start:start + 3])) == 3
    assert all(a != b for a, b in zip(per_word, per_word[1:]))


def test_single_word_rotates_sentences(exercise):
    other = exercise.model_copy(update={"sentence_id": "verb-8-02"})
    deck = Deck([exercise, other])
    seen = [deck.next().sentence_id for _ in range(10)]
    assert all(a != b for a, b in zip(seen, seen[1:]))
    single = Deck([exercise])
    assert single.next() == single.next() == exercise
    with pytest.raises(ValueError, match="at least one"):
        Deck([])


def test_log_identifies_sentence_and_meaning(tmp_path, exercise):
    path = tmp_path / "guesses.jsonl"
    variant = exercise.model_copy(update={"sentence_id": "verb-8-02", "meaning": "secondo uso (test)"})
    append_guess(path, exercise, "gehen", "session", 1)
    append_guess(path, variant, " GEHEN ", "session", 1)
    first, second = [json.loads(line) for line in path.read_text().splitlines()]
    assert first["word_id"] == second["word_id"]
    assert first["sentence_id"] != second["sentence_id"]
    assert "meaning" not in first
    assert second["meaning"] == variant.meaning
    assert second["guess"] == " GEHEN "


def test_load_and_deck(tmp_path, exercise):
    other = exercise.model_copy(update={"word_id": "another", "sentence_id": "another-01"})
    path = tmp_path / "exercises.json"
    path.write_text(json.dumps([exercise.model_dump(), other.model_dump()]))
    deck = Deck(load_exercises(path))
    for _ in range(10):
        first, second = deck.next(), deck.next()
        assert first != second
        assert deck.queue == []
    path.write_text("[]")
    with pytest.raises(ValueError, match="empty"):
        load_exercises(path)
