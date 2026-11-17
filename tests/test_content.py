import json

import pytest

from deutsch.content import import_authored, unmark
from deutsch.core import load_exercises


def files(tmp_path):
    verbs = tmp_path / "verbs.csv"
    verbs.write_text("Rank,Infinitiv\n8,gehen\n52,heißen\n", encoding="utf-8")
    source = tmp_path / "authored.tsv"
    source.write_text("rank\titalian\tgerman\n52\tMi **chiamo** Marco.\tIch **heiße** Marco.\n", encoding="utf-8")
    return source, verbs, tmp_path / "exercises.json"


def test_import_and_repeat(tmp_path):
    source, verbs, output = files(tmp_path)
    assert import_authored([source], verbs, output) == 1
    item = load_exercises(output)[0]
    assert item.infinitive == "heißen"
    assert item.german == "Ich heiße Marco."
    assert item.german_target == "heiße"
    assert item.word_id == "verb-52"
    assert import_authored([source], verbs, output) == 0


def test_import_is_atomic_on_bad_data(tmp_path):
    source, verbs, output = files(tmp_path)
    import_authored([source], verbs, output)
    original = output.read_bytes()
    with source.open("a") as file:
        file.write("8\tIo vado a casa.\tIch **gehe** nach Hause.\n")
    with pytest.raises(ValueError, match="highlighted target"):
        import_authored([source], verbs, output)
    assert output.read_bytes() == original


def test_conflicting_existing_exercise_is_not_replaced(tmp_path):
    source, verbs, output = files(tmp_path)
    import_authored([source], verbs, output)
    text = source.read_text().replace("Marco", "Luca")
    source.write_text(text)
    with pytest.raises(ValueError, match="Refusing to replace"):
        import_authored([source], verbs, output)
    assert load_exercises(output)[0].german == "Ich heiße Marco."


def test_import_variant_preserves_first_sentence(tmp_path):
    source, verbs, output = files(tmp_path)
    import_authored([source], verbs, output)
    original = load_exercises(output)[0]
    row = source.read_text().splitlines()[1]
    source.write_text("rank\titalian\tgerman\tsentence_id\tmeaning\n"
                      + row + "\tverb-52-02\tnome (test)\n", encoding="utf-8")
    assert import_authored([source], verbs, output) == 1
    first, second = load_exercises(output)
    assert first == original
    assert first.word_id == second.word_id
    assert second.sentence_id == "verb-52-02"
    assert second.meaning == "nome (test)"
    assert import_authored([source], verbs, output) == 0
    assert len(load_exercises(output)) == 2


def test_import_rejects_cross_word_sentence_id_collision(tmp_path):
    source, verbs, output = files(tmp_path)
    import_authored([source], verbs, output)
    original = output.read_bytes()
    row = source.read_text().splitlines()[1].replace("52\t", "8\t", 1)
    source.write_text("rank\titalian\tgerman\tsentence_id\n" + row + "\tverb-52-01\n")
    with pytest.raises(ValueError, match="Refusing to replace"):
        import_authored([source], verbs, output)
    assert output.read_bytes() == original


def test_import_phrase_frame(tmp_path):
    source, verbs, output = files(tmp_path)
    source.write_text("rank\titalian\tgerman\tframe\n"
                      "8\t**andare** a casa\tnach Hause **gehen**\tcan\n")
    import_authored([source], verbs, output)
    item = load_exercises(output)[0]
    assert item.italian == "Si può andare a casa."
    assert item.german == "Man kann nach Hause gehen."
    assert item.meaning is None


def test_import_word_id_without_csv_rank(tmp_path):
    source, _, output = files(tmp_path)
    vocabulary = tmp_path / "vocabulary.json"
    vocabulary.write_text(json.dumps([{"word_id": "heissen", "infinitive": "heißen", "meanings": ["nome"]}]))
    source.write_text("word_id\titalian\tgerman\tsentence_id\tmeaning\n"
                      "heissen\tMi **chiamo** Marco.\tIch **heiße** Marco.\theissen-01\tnome\n")
    assert import_authored([source], vocabulary, output) == 1
    imported = load_exercises(output)[0]
    assert imported.word_id == "heissen"
    assert imported.infinitive == "heißen"
    assert imported.meaning == "nome"
    before = output.read_bytes()
    assert import_authored([source], vocabulary, output) == 0
    assert output.read_bytes() == before


def test_import_undeclared_sense_is_atomic(tmp_path):
    source, _, output = files(tmp_path)
    vocabulary = tmp_path / "vocabulary.json"
    vocabulary.write_text(json.dumps([{"word_id": "heissen", "infinitive": "heißen", "meanings": ["nome"]}]))
    source.write_text("word_id\titalian\tgerman\tmeaning\n"
                      "heissen\tMi **chiamo** Marco.\tIch **heiße** Marco.\ttypo\n")
    with pytest.raises(ValueError, match="Undeclared meaning"):
        import_authored([source], vocabulary, output)
    assert not output.exists()


def test_import_requires_vocabulary_entry_first(tmp_path):
    source, _, output = files(tmp_path)
    vocabulary = tmp_path / "vocabulary.json"
    vocabulary.write_text("[]")
    with pytest.raises(ValueError, match="add it to the vocabulary list first"):
        import_authored([source], vocabulary, output)
    assert not output.exists()


def test_import_rejects_conflicting_legacy_rank(tmp_path):
    source, verbs, output = files(tmp_path)
    row = source.read_text().splitlines()[1]
    source.write_text("rank\titalian\tgerman\tword_id\n" + row + "\tverb-8\n")
    with pytest.raises(ValueError, match="Conflicting word_id"):
        import_authored([source], verbs, output)
    assert not output.exists()


@pytest.mark.parametrize("text", ["no target", "**one** and **two**", "****"])
def test_bad_markers(text):
    with pytest.raises(ValueError):
        unmark(text)
