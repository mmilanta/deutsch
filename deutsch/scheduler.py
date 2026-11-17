"""Explainable frequency × need scheduling, without model/API calls."""
from __future__ import annotations

import math
import random
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone

from deutsch.core import Exercise
from deutsch.frequencies import FrequencyTable
from deutsch.history import History, Observation


@dataclass(frozen=True)
class Knowledge:
    mastery: float
    presentations: int
    scored: int
    first_correct: int
    misses: int
    near_misses: int
    gave_up: int
    legacy_estimates: int
    last_result: str | None

    @property
    def need(self) -> float:
        return 1.0 - self.mastery


def estimate_knowledge(observations: list[Observation], now: datetime) -> Knowledge:
    recent = sorted((p for p in observations if p.score is not None), key=lambda p: p.timestamp, reverse=True)[:20]
    successes = evidence = 0.0
    for index, item in enumerate(recent):
        days = max(0.0, (now - item.timestamp).total_seconds() / 86400)
        weight = (0.9 ** index) * math.exp(-math.log(2) * days / 30)
        if item.gave_up:
            weight *= 1.25
        successes += item.score * weight
        evidence += weight
    # A Beta(1,1)-style prior avoids declaring mastery/failure from one attempt.
    # Fractional scores and decay make this a heuristic, not calibrated probability.
    mastery = (1 + successes) / (2 + evidence)
    return Knowledge(
        mastery=mastery, presentations=len(observations), scored=len(recent),
        first_correct=sum(p.first_result == "correct" and not p.gave_up for p in recent),
        misses=sum(p.first_result == "incorrect" and not p.gave_up for p in recent),
        near_misses=sum(p.first_result == "almost_there" and not p.gave_up for p in recent),
        gave_up=sum(p.gave_up for p in recent), legacy_estimates=sum(p.legacy for p in recent),
        last_result=("gave_up" if recent[0].gave_up else recent[0].first_result) if recent else None,
    )


class AdaptiveDeck:
    def __init__(self, exercises: list[Exercise], frequencies: FrequencyTable, history: History,
                 *, new_ratio: float = 0.2, cooldown: int = 5, new_window: int = 100,
                 rng: random.Random | None = None, now=None):
        if not exercises:
            raise ValueError("The deck must contain at least one exercise")
        if not 0 <= new_ratio <= 1 or cooldown < 0 or new_window < 1:
            raise ValueError("Invalid new-word ratio, cooldown, or introduction window")
        self.by_word: dict[str, list[Exercise]] = {}
        for exercise in exercises:
            self.by_word.setdefault(exercise.word_id, []).append(exercise)
        self.frequencies, self.history = frequencies, history
        self.new_ratio, self.cooldown, self.new_window = new_ratio, cooldown, new_window
        self.rng = rng if rng is not None else random.Random()
        self.now = now if now is not None else lambda: datetime.now(timezone.utc)
        self.recent = deque((p.word_id for p in history.presentations if p.word_id in self.by_word), maxlen=cooldown)
        self.variant_queues: dict[tuple[str, str | None], list[Exercise]] = {}
        self.last_sentence: dict[str, str] = {}

    def observations(self, word_id: str) -> list[Observation]:
        return self.history.for_word(word_id, self.by_word[word_id][0].infinitive)

    def senses(self, word_id: str) -> dict[str | None, list[Exercise]]:
        groups: dict[str | None, list[Exercise]] = {}
        for exercise in self.by_word[word_id]:
            groups.setdefault(exercise.meaning, []).append(exercise)
        return groups

    def sense_knowledge(self, word_id: str, meaning: str | None) -> Knowledge:
        return estimate_knowledge([p for p in self.observations(word_id) if p.meaning == meaning], self.now())

    def word_knowledge(self, word_id: str) -> Knowledge:
        # Knowing one sense does not imply knowing another. One word still gets
        # one scheduling weight, irrespective of how many sentences it has.
        return max((self.sense_knowledge(word_id, meaning) for meaning in self.senses(word_id)), key=lambda k: k.need)

    def frequency(self, word_id: str):
        return self.frequencies.for_word(word_id, self.by_word[word_id][0].infinitive)

    def priority(self, word_id: str) -> float:
        return self.frequency(word_id).commonness * self.word_knowledge(word_id).need

    def distribution(self) -> dict[str, float]:
        excluded = list(self.recent)
        eligible = [word for word in self.by_word if word not in excluded]
        # Relax the oldest exclusions first for small decks; never get stuck.
        while not eligible and excluded:
            excluded.pop(0)
            eligible = [word for word in self.by_word if word not in excluded]
        review = [word for word in eligible if self.observations(word)]
        unseen = sorted((word for word in eligible if not self.observations(word)),
                        key=lambda word: (-self.frequency(word).zipf, word))[:self.new_window]
        pools = []
        if review:
            pools.append((review, 1 - self.new_ratio if unseen else 1.0))
        if unseen:
            pools.append((unseen, self.new_ratio if review else 1.0))
        distribution = {}
        for pool, share in pools:
            if share <= 0:
                continue
            total = sum(self.priority(word) for word in pool)
            distribution.update({word: share * self.priority(word) / total for word in pool})
        return distribution

    def next(self) -> Exercise:
        distribution = self.distribution()
        word_id = self.rng.choices(list(distribution), weights=list(distribution.values()), k=1)[0]
        senses = self.senses(word_id)
        meaning = self.rng.choices(list(senses),
                                   weights=[self.sense_knowledge(word_id, m).need for m in senses], k=1)[0]
        variants = self.variant_queues.setdefault((word_id, meaning), [])
        if not variants:
            variants.extend(self.rng.sample(senses[meaning], len(senses[meaning])))
            if len(variants) > 1 and variants[-1].sentence_id == self.last_sentence.get(word_id):
                variants[0], variants[-1] = variants[-1], variants[0]
        exercise = variants.pop()
        self.last_sentence[word_id] = exercise.sentence_id
        self.recent.append(word_id)
        return exercise

    def explain(self, exercise: Exercise) -> str:
        frequency = self.frequency(exercise.word_id)
        knowledge = self.sense_knowledge(exercise.word_id, exercise.meaning)
        band = "common verb" if frequency.zipf >= 5 else "moderate frequency estimate" if frequency.zipf >= 3.5 else "low/uncertain frequency"
        if knowledge.scored:
            evidence = (f"last {knowledge.scored} scored presentations: {knowledge.first_correct} first-try correct, "
                        f"{knowledge.misses} wrong, {knowledge.near_misses} near misses, {knowledge.gave_up} gave up")
        else:
            evidence = "no scored history for this meaning"
        caveat = "; provisional frequency" if frequency.method != "lemma_pos" else ""
        sparse = f"; sparse corpus evidence ({frequency.corpus_count} tokens)" if frequency.method == "lemma_pos" and frequency.corpus_count < 5 else ""
        legacy = "; includes reconstructed legacy attempts" if knowledge.legacy_estimates else ""
        return f"{band}; {evidence}; need {knowledge.need:.0%}{caveat}{sparse}{legacy}"

    def recommendations(self, limit: int = 20) -> list[dict]:
        distribution = self.distribution()
        ranked = sorted(distribution, key=lambda word: (-distribution[word], word))[:limit]
        rows = []
        for word in ranked:
            exercise = max(self.by_word[word], key=lambda e: self.sense_knowledge(word, e.meaning).need)
            frequency, knowledge = self.frequency(word), self.word_knowledge(word)
            rows.append({
                "word_id": word, "infinitive": exercise.infinitive, "meaning": exercise.meaning,
                "bucket": "review" if self.observations(word) else "new",
                "zipf": frequency.zipf, "frequency_method": frequency.method,
                "corpus_count": frequency.corpus_count, "commonness": round(frequency.commonness, 4),
                "mastery_estimate": round(knowledge.mastery, 4), "priority": round(self.priority(word), 4),
                "next_probability": round(distribution[word], 6), "scored_presentations": knowledge.scored,
                "legacy_estimates": knowledge.legacy_estimates, "reason": self.explain(exercise),
            })
        return rows


def offline_report(exercises: list[Exercise], frequencies: FrequencyTable, history: History,
                   *, limit: int = 20, samples: int = 0, seed: int = 42, **options) -> dict:
    deck = AdaptiveDeck(exercises, frequencies, history, rng=random.Random(seed), **options)
    rows = deck.recommendations(limit)
    buckets: Counter[str] = Counter()
    chosen: Counter[str] = Counter()
    for _ in range(samples):
        exercise = deck.next()
        chosen[exercise.word_id] += 1
        buckets["review" if deck.observations(exercise.word_id) else "new"] += 1
    return {
        "eligible_words": len(deck.by_word),
        "seen_words": sum(bool(deck.observations(word)) for word in deck.by_word),
        "frequency_methods": dict(Counter(deck.frequency(word).method for word in deck.by_word)),
        "history_presentations": len(history.presentations),
        "legacy_estimates": sum(p.legacy for p in history.presentations),
        "warnings": history.warnings,
        "settings": {"new_ratio": deck.new_ratio, "cooldown": deck.cooldown, "new_window": deck.new_window},
        "recommendations": rows,
        "simulation": {"samples": samples, "seed": seed, "buckets": dict(buckets),
                       "top_words": chosen.most_common(10),
                       "note": "Frozen-history selection only; no invented answers or writes. Not a learning-outcome evaluation."},
    }
