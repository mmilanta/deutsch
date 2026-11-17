import json
import sys

import pytest

from deutsch.cli import main
from deutsch.core import Exercise
from deutsch.frequencies import Frequency, FrequencyTable
from deutsch.scheduler import AdaptiveDeck


@pytest.fixture
def files(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    exercises = [Exercise(word_id=word, sentence_id=word + "-01", infinitive=word,
                          italian="Io vado.", italian_target="vado", german="Ich gehe.", german_target="gehe")
                 for word in ["gehen", "kommen"]]
    paths = {key: directory / filename for key, filename in
             {"data": "exercises.json", "vocabulary": "vocabulary.json", "frequencies": "frequencies.json",
              "log": "guesses.jsonl", "events": "guesses.events.jsonl"}.items()}
    paths["data"].write_text(json.dumps([e.model_dump() for e in exercises]))
    paths["vocabulary"].write_text(json.dumps([dict(word_id=e.word_id, infinitive=e.infinitive) for e in exercises]))
    table = FrequencyTable(built_at="test", corpus_tokens=1000, sources=[], methodology="test",
                           words={e.word_id: Frequency(infinitive=e.infinitive, zipf=5, method="lemma_pos", corpus_count=10)
                                  for e in exercises})
    paths["frequencies"].write_text(table.model_dump_json())
    return paths


def arguments(files):
    return [arg for key, path in files.items() for arg in [f"--{key}", str(path)]]


def test_recommend_is_offline_read_only_and_supports_json(files, monkeypatch, capsys):
    before = {p: p.read_bytes() for p in files.values() if p.exists()}

    def no_network(*args, **kwargs):
        pytest.fail("Recommendations must not access the network")

    monkeypatch.setattr("deutsch.frequencies.urlopen", no_network)
    monkeypatch.setattr(sys, "argv", ["deutsch", "recommend", *arguments(files), "--json", "--simulate", "10"])
    main()
    report = json.loads(capsys.readouterr().out)
    assert report["eligible_words"] == 2 and report["seen_words"] == 0
    assert report["simulation"]["buckets"] == {"new": 10}
    assert {p: p.read_bytes() for p in files.values() if p.exists()} == before
    assert not files["log"].exists() and not files["events"].exists()


def test_stale_frequency_mapping_warns_to_rebuild(files, monkeypatch, capsys):
    table = json.loads(files["frequencies"].read_text())
    del table["words"]["kommen"]
    files["frequencies"].write_text(json.dumps(table))
    monkeypatch.setattr(sys, "argv", ["deutsch", "recommend", *arguments(files), "--json"])
    main()
    report = json.loads(capsys.readouterr().out)
    assert "Rebuild" in report["warnings"][0]
    assert report["frequency_methods"]["missing"] == 1


def test_known_absence_of_frequency_evidence_does_not_suggest_useless_rebuild(files, monkeypatch, capsys):
    table = json.loads(files["frequencies"].read_text())
    table["words"]["kommen"].update(zipf=0, method="missing", corpus_count=0)
    files["frequencies"].write_text(json.dumps(table))
    monkeypatch.setattr(sys, "argv", ["deutsch", "recommend", *arguments(files), "--json"])
    main()
    report = json.loads(capsys.readouterr().out)
    assert not report["warnings"]
    assert report["frequency_methods"]["missing"] == 1


def test_review_flag_excludes_word_from_adaptive_not_catalog(files, monkeypatch, capsys):
    catalog = json.loads(files["vocabulary"].read_text())
    catalog[0]["review_note"] = "Check lemma"
    files["vocabulary"].write_text(json.dumps(catalog))
    monkeypatch.setattr(sys, "argv", ["deutsch", "recommend", *arguments(files), "--json"])
    main()
    report = json.loads(capsys.readouterr().out)
    assert report["excluded_review_words"] == 1
    assert [r["word_id"] for r in report["recommendations"]] == ["kommen"]
    assert len(json.loads(files["vocabulary"].read_text())) == 2


def test_play_selects_adaptive_deck_only_when_requested(files, monkeypatch):
    captured = []

    class FakeApp:
        def __init__(self, *args, **kwargs):
            captured.append(kwargs)

        def run(self):
            pass

    monkeypatch.setattr("deutsch.tui.DeutschApp", FakeApp)
    monkeypatch.setattr(sys, "argv", ["deutsch", "play", *arguments(files), "--mode", "adaptive", "--explain"])
    main()
    assert isinstance(captured[-1]["deck"], AdaptiveDeck)
    assert captured[-1]["explain"] is True
    assert captured[-1]["events_path"] == files["events"]
    assert captured[-1]["frequencies"] is captured[-1]["deck"].frequencies
    monkeypatch.setattr(sys, "argv", ["deutsch", "play", *arguments(files)])
    main()
    assert captured[-1]["deck"] is None
    assert captured[-1]["frequencies"].words["gehen"].zipf == 5
    files["frequencies"].unlink()
    monkeypatch.setattr(sys, "argv", ["deutsch", "play", *arguments(files)])
    main()
    assert captured[-1]["deck"] is None  # Random needs no frequency file.
    assert captured[-1]["frequencies"] is None


def test_play_forwards_custom_alternative_review_log(files, monkeypatch):
    captured = []

    class FakeApp:
        def __init__(self, *args, **kwargs):
            captured.append(kwargs)

        def run(self):
            pass

    path = files["log"].parent / "review-flags.jsonl"
    monkeypatch.setattr("deutsch.tui.DeutschApp", FakeApp)
    monkeypatch.setattr(sys, "argv", ["deutsch", "play", *arguments(files), "--alternative-log", str(path)])
    main()
    assert captured[-1]["alternative_log"] == path
    assert not path.exists()  # Opening practice alone must not create review flags.


def test_no_subcommand_preserves_random_default(files, monkeypatch):
    captured = []

    class FakeApp:
        def __init__(self, *args, **kwargs):
            captured.append(kwargs)

        def run(self):
            pass

    monkeypatch.chdir(files["data"].parent.parent)
    monkeypatch.setattr("deutsch.tui.DeutschApp", FakeApp)
    monkeypatch.setattr(sys, "argv", ["deutsch"])
    main()
    assert len(captured) == 1 and "deck" not in captured[0]
    assert captured[0]["frequencies"].words["gehen"].zipf == 5
    assert not files["events"].exists()


def test_frequency_build_cannot_overwrite_vocabulary(files, monkeypatch):
    before = files["vocabulary"].read_bytes()
    monkeypatch.setattr(sys, "argv", ["deutsch", "build-frequencies", "--vocabulary", str(files["vocabulary"]),
                                      "--output", str(files["vocabulary"])])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert files["vocabulary"].read_bytes() == before


def test_guess_and_event_paths_must_be_separate(files, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["deutsch", "play", *arguments(files), "--events", str(files["log"])])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not files["log"].exists()


def test_missing_frequency_file_suggests_explicit_build(files, monkeypatch, capsys):
    files["frequencies"].unlink()
    monkeypatch.setattr(sys, "argv", ["deutsch", "recommend", *arguments(files)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "build-frequencies" in capsys.readouterr().err


@pytest.mark.parametrize("command, flags", [
    ("recommend", ["--limit", "0"]), ("recommend", ["--simulate", "-1"]),
    ("recommend", ["--new-ratio", "1.1"]), ("recommend", ["--new-ratio", "nan"]),
    ("recommend", ["--cooldown", "-1"]), ("recommend", ["--new-window", "0"]),
    ("play", ["--explain"]), ("play", ["--threshold", "-1"]),
])
def test_invalid_options_fail_before_writing(files, monkeypatch, command, flags):
    monkeypatch.setattr(sys, "argv", ["deutsch", command, *arguments(files), *flags])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not files["log"].exists() and not files["events"].exists()
