import json
from types import SimpleNamespace

import pytest

from deutsch.core import Exercise, load_exercises
from deutsch.generate import Batch, generate
from deutsch.vocabulary import VocabularyEntry


def exercise(rank=1, infinitive="sein"):
    return Exercise(word_id=f"verb-{rank}", sentence_id=f"verb-{rank}-01", infinitive=infinitive,
                    italian="Io sono qui.", italian_target="sono",
                    german="Ich bin hier.", german_target="bin")


def setup_api(monkeypatch, returned):
    import deutsch.generate as module

    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=Batch(exercises=returned))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(module, "load_dotenv", lambda: None)
    monkeypatch.setattr(module, "load_vocabulary", lambda path: [
        VocabularyEntry(word_id="verb-1", infinitive="sein"),
        VocabularyEntry(word_id="verb-2", infinitive="haben"),
    ])
    monkeypatch.setattr(module, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    return calls


def test_generation_and_resume(tmp_path, monkeypatch):
    calls = setup_api(monkeypatch, [exercise()])
    path = tmp_path / "exercises.json"
    generate(path, 1)
    assert calls[0]["model"] == "gpt-6-luna"
    assert load_exercises(path) == [exercise()]
    generate(path, 1)
    assert len(calls) == 1


def test_generation_preserves_all_existing_variants(tmp_path, monkeypatch):
    first = exercise()
    second = first.model_copy(update={"sentence_id": "verb-1-02", "meaning": "secondo uso (test)"})
    calls = setup_api(monkeypatch, [exercise(2, "haben")])
    path = tmp_path / "exercises.json"
    path.write_text(json.dumps([first.model_dump(exclude_none=True), second.model_dump()]))
    generate(path, 2)
    loaded = {item.sentence_id: item for item in load_exercises(path)}
    assert len(loaded) == 3
    assert loaded[first.sentence_id] == first
    assert loaded[second.sentence_id] == second
    assert len(calls) == 1
    requested = json.loads(calls[0]["input"][1]["content"])
    assert requested == [{"word_id": "verb-2", "infinitive": "haben"}]


def test_generation_uses_custom_local_catalog(tmp_path, monkeypatch):
    import deutsch.generate as module
    from deutsch.vocabulary import load_vocabulary

    item = exercise().model_copy(update={"word_id": "custom", "sentence_id": "custom-01"})
    calls = setup_api(monkeypatch, [item])
    monkeypatch.setattr(module, "load_vocabulary", load_vocabulary)
    vocabulary = tmp_path / "vocabulary.json"
    vocabulary.write_text(json.dumps([{"word_id": "custom", "infinitive": "sein"}]))
    output = tmp_path / "exercises.json"
    generate(output, 1, vocabulary=vocabulary)
    assert json.loads(calls[0]["input"][1]["content"]) == [{"word_id": "custom", "infinitive": "sein"}]
    assert load_exercises(output) == [item]


def test_generation_does_not_invent_review_entries(tmp_path, monkeypatch):
    import deutsch.generate as module

    calls = setup_api(monkeypatch, [])
    monkeypatch.setattr(module, "load_vocabulary", lambda path: [
        VocabularyEntry(word_id="review", infinitive="test", review_note="verify this entry"),
    ])
    output = tmp_path / "exercises.json"
    generate(output, 1)
    assert calls == []
    assert not output.exists()


def test_invalid_batch_does_not_overwrite(tmp_path, monkeypatch):
    setup_api(monkeypatch, [exercise(2, "wrong-infinitive")])
    path = tmp_path / "exercises.json"
    original = json.dumps([exercise().model_dump()])
    path.write_text(original)
    with pytest.raises(ValueError, match="changed an infinitive"):
        generate(path, 2)
    assert path.read_text() == original


def test_missing_batch_is_rejected(tmp_path, monkeypatch):
    setup_api(monkeypatch, [])
    path = tmp_path / "exercises.json"
    with pytest.raises(ValueError, match="missing, duplicate, or unexpected"):
        generate(path, 1)
    assert not path.exists()
