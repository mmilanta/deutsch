import hashlib
import json
import sys
from collections import Counter
from types import SimpleNamespace

import pytest

from deutsch import frequencies
from deutsch.frequencies import Frequency, FrequencyTable, count_corpus, estimate_frequencies, load_frequencies
from deutsch.vocabulary import VocabularyEntry


def row(identifier, form, lemma, pos, head="0", relation="root"):
    return "\t".join([str(identifier), form, lemma, pos, "_", "_", str(head), relation, "_", "_"]) + "\n"


def test_counts_lemmas_pos_and_separable_particles_not_homographs(tmp_path):
    path = tmp_path / "corpus.conllu"
    path.write_text(
        "# test\n" + row(1, "einen", "ein", "DET") + row(2, "Firmen", "Firma", "NOUN") +
        row(3, "ging", "gehen", "VERB") + row(4, ".", ".", "PUNCT") + "\n" +
        row(1, "geht", "gehen", "VERB") + row(2, "ist", "sein", "AUX", 1, "aux") + "\n" +
        row(1, "steht", "stehen", "VERB") + row(2, "auf", "auf", "ADP", 1, "compound:prt") + "\n" +
        row(1, "aufstehen", "aufstehen", "VERB") + row(2, "auf", "auf", "ADP", 1, "compound:prt") + "\n" +
        row("1-2", "zum", "_", "_") + row(1, "zu", "zu", "ADP") + row(2, "dem", "der", "DET") +
        row("2.1", "empty", "gehen", "VERB"), encoding="utf-8")
    counts, tokens = count_corpus([path])
    assert counts == Counter({"gehen": 2, "sein": 1, "aufstehen": 2})
    assert "einen" not in counts and "firmen" not in counts
    assert tokens == 11


def test_ambiguous_and_missing_lemmas_are_not_guessed(tmp_path):
    path = tmp_path / "corpus.conllu"
    path.write_text(row(1, "winden", "Wind|Winden", "VERB") + row(2, "foo", "_", "VERB"))
    assert count_corpus([path]) == (Counter(), 2)


@pytest.mark.parametrize("body", ["", "1\tbroken\n"])
def test_bad_or_empty_corpus_rejected(tmp_path, body):
    path = tmp_path / "bad.conllu"
    path.write_text(body)
    with pytest.raises(ValueError):
        count_corpus([path])


def test_fallback_caps_homographic_surface_frequencies():
    entries = [VocabularyEntry(word_id=word, infinitive=word) for word in ["gehen", "einen", "unknown"]]
    words = estimate_frequencies(entries, Counter({"gehen": 100}), 100_000,
                                 lambda word: {"gehen": 5, "einen": 7, "unknown": 0}[word])
    assert words["gehen"].zipf == 6 and words["gehen"].method == "lemma_pos"
    assert words["einen"].zipf == 2.5 and words["einen"].surface_zipf == 7
    assert words["unknown"].method == "missing"
    assert words["gehen"].commonness > words["einen"].commonness > words["unknown"].commonness > 0


def test_frequency_weights_are_bounded_and_invalid_scores_rejected():
    for score in [0, 2, 3, 5, 7, 9]:
        assert 0.1 <= Frequency(infinitive="gehen", zipf=score, method="lemma_pos").commonness <= 1
    for score in [float("nan"), float("inf"), -1, 10]:
        with pytest.raises(ValueError):
            Frequency(infinitive="gehen", zipf=score, method="lemma_pos")


def test_stale_word_id_or_changed_infinitive_has_conservative_fallback(tmp_path):
    table = FrequencyTable(built_at="test", corpus_tokens=10, sources=[], methodology="test",
                           words={"x": Frequency(infinitive="gehen", zipf=6, method="lemma_pos")})
    assert table.for_word("x", "kommen").method == "missing"
    assert table.for_word("new", "gehen").zipf == 0
    path = tmp_path / "frequencies.json"
    path.write_text(table.model_dump_json())
    assert load_frequencies(path) == table
    path.write_text(json.dumps(table.model_dump() | {"schema_version": 999}))
    with pytest.raises(ValueError, match="Unsupported"):
        load_frequencies(path)


def test_rebuild_uses_cached_corpus_and_embeds_attribution(tmp_path, monkeypatch):
    cache, output = tmp_path / "cache", tmp_path / "frequencies.json"
    cache.mkdir()
    corpus = cache / "test.conllu"
    corpus.write_text(row(1, "ging", "gehen", "VERB"))
    monkeypatch.setattr(frequencies, "UD_FILES", [corpus.name])
    monkeypatch.setattr(frequencies, "version", lambda name: "test")
    monkeypatch.setitem(sys.modules, "wordfreq", SimpleNamespace(zipf_frequency=lambda word, lang: 5))

    def no_download(*args, **kwargs):
        pytest.fail("Cached rebuild must not access the network")

    monkeypatch.setattr(frequencies, "urlopen", no_download)
    table = frequencies.build_frequencies([VocabularyEntry(word_id="gehen", infinitive="gehen")], output, cache)
    assert load_frequencies(output) == table
    assert table.words["gehen"].corpus_count == 1
    assert table.sources[0]["sha256"] == hashlib.sha256(corpus.read_bytes()).hexdigest()
    assert table.sources[0]["license"] == "CC BY-SA 4.0"
    assert "McDonald" in table.sources[0]["citation"]
    assert "SUBTLEX" in table.sources[-1]["subtlex_credit"]
    assert not output.with_suffix(".json.tmp").exists()
