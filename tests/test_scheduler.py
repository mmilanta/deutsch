import random
from datetime import datetime, timedelta, timezone

import pytest

from deutsch.core import Exercise
from deutsch.frequencies import Frequency, FrequencyTable
from deutsch.history import History, Observation
from deutsch.scheduler import AdaptiveDeck, estimate_knowledge, offline_report

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def exercise(word="gehen", *, sentence=None, meaning=None):
    return Exercise(word_id=word, sentence_id=sentence or word + "-01", infinitive=word,
                    italian="Io vado.", italian_target="vado", german="Ich gehe.", german_target="gehe", meaning=meaning)


def table(words):
    return FrequencyTable(built_at=NOW.isoformat(), corpus_tokens=1000, sources=[], methodology="test",
                          words={word: Frequency(infinitive=word, zipf=score, method="lemma_pos", corpus_count=20)
                                 for word, score in words.items()})


def observation(word="gehen", result="correct", *, index=0, days=0, meaning=None, gave_up=False):
    return Observation(str(index), word, word + "-01", NOW - timedelta(days=days, seconds=index),
                       meaning=meaning, first_result=result, gave_up=gave_up)


def deck(words=None, history=None, **options):
    words = words or {"gehen": 5, "kommen": 5}
    return AdaptiveDeck([exercise(word) for word in words], table(words), history or History(),
                        rng=random.Random(42), now=lambda: NOW, **options)


def test_knowledge_orders_correct_near_wrong_and_giveup():
    results = [estimate_knowledge([observation(result=r)], NOW).mastery
               for r in ["correct", "almost_there", "incorrect"]]
    gave_up = estimate_knowledge([observation(result=None, gave_up=True)], NOW).mastery
    assert results[0] > results[1] > results[2] > gave_up
    assert results[1] == estimate_knowledge([], NOW).mastery == 0.5


def test_unanswered_quit_is_not_failure_or_success():
    stats = estimate_knowledge([observation(result=None)], NOW)
    assert stats.mastery == 0.5
    assert stats.presentations == 1 and stats.scored == 0


def test_recent_evidence_counts_more_and_old_evidence_fades():
    a = estimate_knowledge([observation(result="correct"), observation(result="incorrect", days=10)], NOW)
    b = estimate_knowledge([observation(result="incorrect"), observation(result="correct", days=10)], NOW)
    old = estimate_knowledge([observation(days=365)], NOW)
    assert a.mastery > b.mastery
    assert abs(old.mastery - 0.5) < 0.001


def test_repeated_success_never_reaches_absolute_mastery_and_history_is_bounded():
    stats = estimate_knowledge([observation(index=i) for i in range(100)], NOW)
    assert 0.8 < stats.mastery < 1
    assert stats.scored == 20 and stats.presentations == 100


def test_frequency_and_weakness_each_increase_priority():
    history = History([observation("weak", "incorrect"), observation("strong", "correct")])
    d = deck({"weak": 5, "strong": 5, "rare": 2, "common": 6}, history, cooldown=0)
    assert d.priority("weak") > d.priority("strong")
    assert d.priority("common") > d.priority("rare")
    assert d.priority("rare") > 0


def test_review_new_split_and_pool_fallbacks():
    d = deck(history=History([observation()]), cooldown=0)
    assert d.distribution() == pytest.approx({"gehen": 0.8, "kommen": 0.2})
    assert sum(deck(cooldown=0).distribution().values()) == pytest.approx(1)
    assert deck({"gehen": 5}, History([observation()]), cooldown=0).distribution() == {"gehen": 1}


@pytest.mark.parametrize("ratio, expected", [(0, {"gehen": 1}), (1, {"kommen": 1})])
def test_extreme_ratios_work_when_both_buckets_exist(ratio, expected):
    d = deck(history=History([observation()]), cooldown=0, new_ratio=ratio)
    assert d.distribution() == expected


def test_new_words_come_from_most_common_unseen_window():
    d = deck({"rare": 2, "common": 6, "middle": 4}, new_window=2)
    assert set(d.distribution()) == {"common", "middle"}


def test_cooldown_avoids_last_five_and_relaxes_for_small_decks():
    d = deck({f"word{i}": 5 for i in range(8)}, cooldown=5)
    seen = []
    for _ in range(100):
        word = d.next().word_id
        assert word not in seen[-5:]
        seen.append(word)
    d = deck(cooldown=5)
    seen = [d.next().word_id for _ in range(20)]
    assert all(a != b for a, b in zip(seen, seen[1:]))
    d = deck({"gehen": 5}, cooldown=5)
    assert d.next() == d.next()


def test_cooldown_survives_restart_from_history():
    d = deck({f"word{i}": 5 for i in range(8)},
             History([observation(f"word{i}", index=4-i) for i in range(5)]), cooldown=5)
    assert set(d.distribution()) == {"word5", "word6", "word7"}


def test_variant_count_does_not_inflate_word_weight_and_variants_rotate():
    exercises = [exercise(sentence=f"gehen-{i}") for i in range(5)] + [exercise("kommen")]
    d = AdaptiveDeck(exercises, table({"gehen": 5, "kommen": 5}), History(), cooldown=0, rng=random.Random(2))
    assert d.distribution() == pytest.approx({"gehen": 0.5, "kommen": 0.5})
    variants = []
    for _ in range(100):
        e = d.next()
        if e.word_id == "gehen":
            variants.append(e.sentence_id)
    assert all(a != b for a, b in zip(variants, variants[1:]))
    for i in range(0, len(variants) - 4, 5):
        assert len(set(variants[i:i+5])) == 5


def test_learning_one_meaning_does_not_master_another():
    exercises = [exercise(sentence="a", meaning="a"), exercise(sentence="b", meaning="b")]
    h = History([observation(meaning="a", index=i) for i in range(20)])
    d = AdaptiveDeck(exercises, table({"gehen": 5}), h, now=lambda: NOW)
    assert d.sense_knowledge("gehen", "a").mastery > 0.8
    assert d.sense_knowledge("gehen", "b").mastery == 0.5
    assert d.word_knowledge("gehen").mastery == 0.5
    assert d.recommendations()[0]["meaning"] == "b"


def test_same_session_results_update_selection_without_restart():
    h = History()
    d = deck(history=h, cooldown=0)
    assert d.distribution()["gehen"] == pytest.approx(0.5)
    h.add(observation(result="incorrect"))
    assert d.distribution()["gehen"] == pytest.approx(0.8)
    assert d.word_knowledge("gehen").mastery < 0.5


def test_offline_preview_and_simulation_are_read_only_and_seeded():
    h = History([observation()])
    exercises, frequencies = [exercise(), exercise("kommen")], table({"gehen": 5, "kommen": 5})
    a = offline_report(exercises, frequencies, h, samples=1000, seed=5, cooldown=0, now=lambda: NOW)
    b = offline_report(exercises, frequencies, h, samples=1000, seed=5, cooldown=0, now=lambda: NOW)
    assert a == b
    assert 750 < a["simulation"]["buckets"]["review"] < 850
    assert len(h.presentations) == 1
    assert not h.warnings


@pytest.mark.parametrize("options", [{"new_ratio": -1}, {"new_ratio": 2}, {"new_ratio": float("nan")},
                                     {"cooldown": -1}, {"new_window": 0}])
def test_invalid_settings_rejected(options):
    with pytest.raises(ValueError):
        deck(**options)


def test_explanations_do_not_reveal_target_or_meaning():
    e = exercise(word="verheimlichen", meaning="nascondere (test)")
    d = AdaptiveDeck([e], table({e.word_id: 4}), History())
    reason = d.explain(e)
    assert e.infinitive not in reason and e.meaning not in reason
    assert "no scored history" in reason
