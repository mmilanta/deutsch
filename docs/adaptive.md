# Adaptive practice

## Commands

```sh
# Existing random, word-balanced rounds remain the default.
uv run deutsch
uv run deutsch play --mode random

# New, optional adaptive mode; normal inline UI and infinitive answers.
uv run deutsch play --mode adaptive
uv run deutsch play --mode adaptive --explain

# Read-only inspection. Neither command writes history or accesses the network.
uv run deutsch recommend --limit 20
uv run deutsch recommend --simulate 1000 --seed 42 --json
```

The explanation printed before an exercise never includes the answer or its meaning label. The preview report intentionally does name candidate words; it is an inspection tool, not an exercise.

## 1. Frequency

The separately versioned `data/frequencies.json` contains canonical word IDs/infinitives, estimated Zipf frequency, corpus counts, method, source URLs/versions/checksums, and attribution. It contains no user history. It does not change the canonical vocabulary, sentence IDs, or exercise content.

Primary estimates count **VERB/AUX lemmas** in all three splits of **UD German GSD r2.16**. This pools inflected forms without counting homographic articles, pronouns, or nouns as verbs. Separable `compound:prt` particles are restored to the lemma, where annotated. Zipf is `log10(occurrences / corpus_word_tokens × 1 billion)`, with punctuation and symbols excluded from the denominator. All splits are used for frequency counts; this is not training or evaluating a language model.

If a verb has no corpus occurrences, use an infinitive lookup from `wordfreq`, **capped at Zipf 2.5**. This is a conservative fallback, not a statistically calibrated estimate: a frequent homographic article must not promote a verb to the top. Zero/missing evidence gets the minimum positive selection weight. Preserve the uncapped surface lookup separately for inspection. An absent/stale word-ID/infinitive cache entry also receives minimum weight and a rebuild warning.

Limitations: GSD is a small news/reviews/web corpus, lemmas are automatically annotated, single occurrences are weak evidence, and separable constructions may be missed or misanalysed. `wordfreq` is a broader multi-source snapshot through approximately 2021 but not a verb-lemma frequency source. These mixed-source priorities should not be presented as precise population frequency measurements. No original CSV ranks are used for adaptive scoring.

## 2. Knowledge evidence

One scored observation per **presentation**, not per guess:

| Presentation evidence | Score |
| --- | --- |
| First attempt correct | 1 |
| First attempt almost there | 0.5 |
| First attempt incorrect | 0 |
| Explicit give-up/reveal | 0, with evidence weight ×1.25 |
| No attempt, then quit/EOF/interrupt | Unscored |

A later correct retry does not turn an initial miss into successful recall. Explicitly giving up overrides any near-miss credit. If the first guess is missing and no terminal event supplies it, later guesses cannot establish first-attempt performance.

Use the latest 20 scored presentations per word/labelled meaning. For each, calculate:

```text
weight = 0.9^recency_index × 2^(-age_in_days / 30)
mastery_estimate = (1 + sum(score × weight)) / (2 + sum(weight))
need = 1 - mastery_estimate
```

Multiply `weight` by 1.25 for explicit give-ups. The prior starts unseen/unscored material at 0.5 and prevents absolute certainty after a few attempts. Older evidence fades towards uncertainty; newer evidence matters more. This is an interpretable heuristic, **not a calibrated probability or a full spaced-repetition model**.

Knowledge is tracked by word ID and optional meaning label. Multiple unlabelled examples share word knowledge. Different labelled meanings do not share evidence: the word's priority uses its weakest covered meaning, and meaning selection is weighted by need. Sentence variants rotate within each meaning. Uncovered words/meanings cannot be practised until exercises exist; the selector does not author any.

Strict target checking has limitations: a valid synonym, ambiguous prompt, or typo can look like lack of knowledge. No linguistic quality or human review is implied by structurally valid content. Near misses get partial evidence, but the selector cannot perfectly distinguish spelling from recall difficulty.

## 3. Frequency × need

```text
commonness = 0.1 + 0.9 × clamp((zipf - 2) / 4, 0, 1)
priority = commonness × need
```

Bounded, logarithmic frequency influence avoids raw occurrence counts letting `sein` dominate everything. Sample with weighted randomness, not a greedy highest-priority choice. Each word has one weight irrespective of sentence count. All scored words retain a nonzero chance of review.

## 4. New words and cooldown

- Target **80% previously presented words / 20% unseen words** when both eligible pools exist. Previously presented does not mean mastered.
- Introduce unseen words from the **100 most frequent remaining eligible words**, weighted by priority. This prevents thousands of rare unseen entries collectively crowding out a smaller set of common ones. The window advances as words are presented.
- Avoid the **last five presented/selected word IDs**, including recent history from earlier sessions. If a small deck exhausts the choices, relax the oldest cooldown exclusions first. A one-word deck still works.
- If either pool is unavailable, use the other. Cold starts therefore introduce new words; the nominal quota is not a promise for every small batch.
- Exclude canonical entries with unresolved `review_note` from adaptive mode. Random mode is unchanged.

Tune both `play` and `recommend` with:

```sh
uv run deutsch play --mode adaptive --new-ratio 0.3 --cooldown 7 --new-window 100
```

`--new-ratio` is 0..1, `--cooldown` is nonnegative, and `--new-window` is positive. These are experimental teaching parameters. If review feels excessive or new words arrive too slowly, inspect the report and adjust the ratio rather than assuming the defaults are optimal. `play --seed N` gives reproducible choices against the same history and clock; report simulations default to seed 42.

## 5. Append-only history

Existing `data/guesses.jsonl` remains untouched except for real future guesses. New guesses use schema v2 and add a UUID `presentation_id`; exact raw input, result, attempt, and existing fields are preserved. Standalone legacy calls without a presentation ID still produce schema v1.

Both modes write a separate schema-v1 event log, defaulting to `data/guesses.events.jsonl`. Events are `presented`, `completed`, `gave_up`, and `abandoned`. They carry presentation/session/word/sentence IDs, UTC timestamps, the expected infinitive and optional meaning; terminal events include attempt count and the first result, if any. This preserves learning evidence even if only the event file is available. Loading both files deduplicates by presentation ID.

Custom `--log PATH` derives `<stem>.events.jsonl` next to it; `--events PATH` overrides that. Never point both options at the same file. Keep both files private and backed up together. At the user's explicit request, project logs under `data/` are intentionally versioned in this private GitHub repository, including raw guesses, presentation events, generation logs, and ambiguity flags when present. This is personal learning history; do not upload it elsewhere without permission or commit credentials. Practice never pushes/uploads automatically. Recommendation JSON exports also contain personal statistics and remain excluded by default. Default `data/recommendations*.json` exports are ignored too.

Legacy v1 retries are approximately grouped by consecutive session/word/sentence IDs and increasing attempt numbers. Resetting attempts or changing the key starts a new presentation. Old reveals, unattempted prompts, and response times were not recorded; do not invent them or infer mastery from missing mistakes. History is never rewritten for migration. Invalid/truncated records and unsupported schemas are skipped with visible warnings, preserving the original file. An unattempted abandoned/incomplete presentation adds no success or failure evidence.

New results update the active session immediately. Failed guess writes permit retry without counting an unsaved answer. Failed presentation-event writes are visible and stop the session; already saved guesses remain available for recovery.

## 6. Offline validation

`recommend` reports eligible/seen counts, frequency coverage, legacy reconstruction/warnings, candidate priorities, estimated mastery, next-selection probabilities after cooldown/quota/window filtering, and human-readable reasons. Reports do not change any files.

`--simulate N` samples repeated selections with cooldowns against **frozen history**. It invents no learner answers, so unseen words remain unseen during the simulation. Its review/new split and distribution are a selector smoke test, not evidence that learning outcomes improve. Actual prompts update history; this simulation deliberately does not.

Validation checks:

- Common weak words outrank equally frequent stronger words.
- Equally weak common words outrank rare words.
- Retries do not inflate successful recall.
- Give-up events affect need; unattempted quits do not.
- Unseen common words appear; rare mass and sentence counts do not dominate.
- Known senses do not incorrectly establish mastery of other senses.
- Cooldowns and pool fallback work for small decks.
- Runtime use is offline and inspection/simulation never writes user history.

Automated tests use temporary data only. No default-mode change is made on the strength of an offline preview; random and adaptive modes remain available for comparison.

## Rebuilding / custom decks

The shipped frequency artifact makes runtime use dependency-light and offline. Only an explicit rebuild needs the optional `wordfreq` package and initial public downloads:

```sh
uv run --extra frequency deutsch build-frequencies
# Custom catalog and destination:
uv run --extra frequency deutsch build-frequencies --vocabulary my-vocabulary.json --output my-frequencies.json
uv run deutsch play --mode adaptive --vocabulary my-vocabulary.json --data my-exercises.json --frequencies my-frequencies.json --log my-guesses.jsonl
```

Corpus files are cached in ignored `.cache/deutsch-frequency/`; use `build-frequencies --cache PATH` to override it. Later rebuilds use that cache without downloading. Output is replaced atomically after successful parsing/scoring. Frequency construction only uses public corpus and canonical vocabulary data, never guesses or secrets, and makes no paid/model API calls. See [provenance and licensing](../data/FREQUENCIES.md).

Future grammar principal forms and bonus/partial-credit scoring remain a [TODO](../TODO.md), not part of adaptive scheduling or current answers.
