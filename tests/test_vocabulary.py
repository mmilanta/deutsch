import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from deutsch.cli import main
from deutsch.core import Exercise, load_exercises
from deutsch.vocabulary import VocabularyEntry, audit_vocabulary, check_vocabulary, load_vocabulary


def sentence(**updates):
    fields = dict(word_id="gehen", sentence_id="gehen-01", infinitive="gehen",
                  italian="Io vado a casa.", italian_target="vado",
                  german="Ich gehe nach Hause.", german_target="gehe")
    return Exercise(**(fields | updates))


def test_single_pair_is_sufficient():
    entry = VocabularyEntry(word_id="gehen", infinitive="gehen")
    report = audit_vocabulary([entry], [sentence()])
    assert report.complete
    assert report.covered_word_count == report.vocabulary_count == 1
    assert not report.missing_meanings


def test_missing_entries_keep_review_notes():
    entries = [VocabularyEntry(word_id="gehen", infinitive="gehen"),
               VocabularyEntry(word_id="review", infinitive="test", review_note="da verificare")]
    report = audit_vocabulary(entries, [sentence()])
    assert not report.complete
    assert report.missing_words == [entries[1]]
    assert report.missing_words[0].review_note == "da verificare"
    assert not report.errors  # A review note is visible, not falsely marked covered.


def test_required_meanings_and_variants():
    entry = VocabularyEntry(word_id="gehen", infinitive="gehen", meanings=["uso uno", "uso due"])
    first = sentence(meaning="uso uno")
    duplicate_sense = sentence(sentence_id="gehen-02", meaning="uso uno")
    report = audit_vocabulary([entry], [first, duplicate_sense])
    assert not report.missing_words
    assert [m.meaning for m in report.missing_meanings] == ["uso due"]
    second = sentence(sentence_id="gehen-03", meaning="uso due")
    assert audit_vocabulary([entry], [first, duplicate_sense, second]).complete
    # An unlabeled legacy sentence does not silently satisfy a newly declared sense.
    assert len(audit_vocabulary([entry], [sentence()]).missing_meanings) == 2


def test_broken_links_are_not_counted_as_coverage():
    entry = VocabularyEntry(word_id="gehen", infinitive="gehen", meanings=["uso"])
    report = audit_vocabulary([entry], [sentence(word_id="unknown"),
                                      sentence(sentence_id="other", infinitive="kommen"),
                                      sentence(sentence_id="third", meaning="typo")])
    assert report.covered_word_count == 0
    assert report.missing_words == [entry]
    assert len(report.errors) == 3
    assert "Unknown word ID" in report.errors[0]
    assert "Infinitive mismatch" in report.errors[1]
    assert "Undeclared meaning" in report.errors[2]


def test_duplicate_ids_fail():
    entry = VocabularyEntry(word_id="gehen", infinitive="gehen")
    with pytest.raises(ValueError, match="Duplicate word IDs"):
        audit_vocabulary([entry, entry], [])
    report = audit_vocabulary([entry], [sentence(), sentence()])
    assert report.errors == ["Duplicate sentence ID: gehen-01"]


@pytest.mark.parametrize("updates", [
    {"word_id": "bad id"}, {"infinitive": " "}, {"infinitive": " gehen"},
    {"meanings": [""]}, {"meanings": [" uso"]}, {"meanings": ["uso", "uso"]},
])
def test_bad_catalog_entries(updates):
    with pytest.raises(ValidationError):
        VocabularyEntry(**({"word_id": "gehen", "infinitive": "gehen"} | updates))


def test_read_only_coverage_and_missing_sentence_file(tmp_path):
    vocabulary = tmp_path / "vocabulary.json"
    data = tmp_path / "exercises.json"
    vocabulary.write_text(json.dumps([{"word_id": "gehen", "infinitive": "gehen"}]))
    original = vocabulary.read_bytes()
    report = check_vocabulary(vocabulary, data)
    assert len(report.missing_words) == 1
    assert not data.exists()
    assert vocabulary.read_bytes() == original
    data.write_text("[]")
    assert not check_vocabulary(vocabulary, data).complete
    assert load_exercises(data, allow_empty=True) == []
    data.write_text(json.dumps([sentence().model_dump(exclude_none=True)]))
    before = data.read_bytes()
    assert check_vocabulary(vocabulary, data).complete
    assert data.read_bytes() == before


def test_catalog_file_validation(tmp_path):
    path = tmp_path / "vocabulary.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="JSON list"):
        load_vocabulary(path)
    entry = {"word_id": "gehen", "infinitive": "gehen"}
    path.write_text(json.dumps([entry, entry]))
    with pytest.raises(ValueError, match="Duplicate word IDs"):
        load_vocabulary(path)


def test_check_cli_exit_statuses_and_json(tmp_path, monkeypatch, capsys):
    vocabulary = tmp_path / "vocabulary.json"
    data = tmp_path / "exercises.json"
    vocabulary.write_text(json.dumps([{"word_id": "gehen", "infinitive": "gehen"}]))
    argv = ["deutsch", "check-vocabulary", "--vocabulary", str(vocabulary), "--data", str(data), "--json"]
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["missing_words"][0]["word_id"] == "gehen"
    data.write_text(json.dumps([sentence().model_dump(exclude_none=True)]))
    main()
    assert json.loads(capsys.readouterr().out)["covered_word_count"] == 1
    data.write_text(json.dumps([sentence(word_id="unknown").model_dump(exclude_none=True)]))
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert json.loads(capsys.readouterr().out)["errors"]
    data.write_text("not json")
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert "Error:" in capsys.readouterr().err


def test_skill_files_are_project_local():
    root = Path(__file__).resolve().parents[1]
    directory = root / ".agents/skills/complete-vocabulary"
    text = (directory / "SKILL.md").read_text()
    assert text.startswith("---\nname: complete-vocabulary\ndescription: ")
    assert (directory / "references/format.md").is_file()
    assert (directory / "../../..").resolve() == root
    assert "check-vocabulary" in text
    assert "no new sentences" in text
