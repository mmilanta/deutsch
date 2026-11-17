# Deutsch

Minimal, inline terminal practice for Italian speakers learning German verbs. Read an Italian sentence, then recall the German **infinitive**. Just a prompt, bold words, and a little color—no full-screen UI, browser, account, or backend. Previous exercises stay in your terminal scrollback.

## Run

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). From this directory:

```sh
uv sync
uv run deutsch
```

The cached exercises in `data/exercises.json` work offline. Generation is the only step that calls OpenAI.

### Controls

- Type the German infinitive at `> ` and press **Enter** to submit.
- Press **Enter on an empty line** to give up and reveal the full German sentence.
- Type **/q** to quit; Ctrl+C or end-of-input also exits cleanly.
- Type **/alternative** (or **/alt**) to flag the **previous completed/revealed exercise in this session**, not the currently displayed prompt, for possible alternative translations. The current prompt stays open; the command is not a guess or scored attempt.

After a correct answer or a reveal, the next exercise is printed below. Nothing is cleared or redrawn.

Correct guesses automatically reveal the translation, with the German verb in **bold** and the expected infinitive underneath. Both modes show a muted **popularity number** beside the revealed translation: higher means more common, using the stored frequency estimate rather than your mastery score. `n/d` means no usable frequency estimate is available. This also appears when giving up, but not before revealing the answer. A one-edit near miss gets **Almost there**; near misses and wrong answers allow another attempt without revealing the answer. Insertion, deletion, and substitution each count as one edit; a transposition usually counts as two.

German content retains **standard German spelling**, including `ß` (`heißen`, `weiß`, `Straße`). Both `ss` and `ß` spellings are accepted as correct when checking answers (`heissen` and `heißen`); raw guesses are still logged unchanged.

Checking ignores leading/trailing whitespace and capitalization, normalizes Unicode, and keeps German umlauts significant (`konnen` is a near miss for `können`, not correct). Set `--threshold 0` to disable near misses, or increase it:

```sh
uv run deutsch play --threshold 1
NO_COLOR=1 uv run deutsch
```

Use a terminal supporting bold and Unicode for the best experience. Output uses your normal terminal background and scrollback; feedback also has text labels for monochrome use.

## Adaptive practice: common words you need to practise

The original random mode remains the default. Opt into adaptive selection with:

```sh
uv run deutsch play --mode adaptive
uv run deutsch play --mode adaptive --explain
```

Adaptive mode combines **verb frequency × estimated need for practice**. It targets 80% review / 20% new words, introduces unseen words from a window of the 100 most common remaining candidates, and avoids the last five words when possible. Correct first attempts reduce priority; wrong answers, near misses, and giving up provide different evidence. A successful retry is not counted as successful first-attempt recall. Multiple sentence variants do not multiply a word's scheduling weight; labelled meanings have separate knowledge estimates.

Preview recommendations without writing logs or starting practice:

```sh
uv run deutsch recommend --limit 20
uv run deutsch recommend --simulate 1000 --seed 42 --json
```

Both practice and recommendations are fully **offline**, using the included `data/frequencies.json`. Estimates primarily count verb/auxiliary **lemmas and parts of speech**, rather than trusting the old CSV ranking or raw infinitive frequency. Missing corpus evidence uses a conservative, explicitly provisional `wordfreq` fallback. Corpus coverage and automatic annotation are imperfect; these are rough teaching priorities, not a definitive popularity ranking or calibrated mastery probabilities. Words flagged with `review_note` are excluded from adaptive mode.

Rebuilding frequency metadata is optional and explicit; it downloads public corpus files once (~22 MB), caches them locally, and requires an extra build dependency:

```sh
uv run --extra frequency deutsch build-frequencies
```

See [the algorithm, logging, and tuning details](docs/adaptive.md) and [frequency provenance/licensing](data/FREQUENCIES.md). Future grammar forms and partial-credit scoring are recorded in [TODO.md](TODO.md), **not implemented**.

## Vocabulary list and completion skill

```text
data/vocabulary.json                       # canonical list of vocabulary words
data/exercises.json                        # linked Italian/German sentence pairs
data/authored*.tsv                          # editable sentence batches
.agents/skills/complete-vocabulary/SKILL.md  # agent workflow for missing pairs
```

Add new words to **`data/vocabulary.json`**, not the old CSV. V0 teaches verbs: each entry needs a stable, unique `word_id` and the German `infinitive`. IDs do not need numeric ranks. Do not renumber existing IDs: exercises and guess history refer to them.

Optional fields:

- `meanings`: Italian labels for distinct senses that should each have an example. Omit for a word where one ordinary sentence is enough.
- `review_note`: an unresolved lexical issue. It stays visible in the coverage report rather than being silently marked covered.

Check coverage without changing anything or calling an API:

```sh
uv run deutsch check-vocabulary
uv run deutsch check-vocabulary --json
```

Exit codes: **0** complete, **1** missing words/meanings, **2** invalid data or broken links. The check verifies IDs, canonical answers, and declared meaning coverage; it cannot certify linguistic quality. An absent exercise file is treated as all vocabulary missing, so the workflow also works from an empty deck.

To have the coding agent fill missing entries, use the project skill:

```text
/skill:complete-vocabulary
```

In Pi, run `/reload` once after this newly installed skill is added. The skill is also available to agents that discover project `.agents/skills/` directories. It audits first, writes missing pairs directly in reviewed batches, imports them, and checks again. It preserves existing sentences/history and reports uncertain vocabulary rather than inventing meanings. A check-only or no-new-sentences request remains read-only. This is an **agent workflow**, not a background service or automatic API call when you launch practice.

Practice, the default importer, the checker, and optional API generation now all use the canonical list. The original `data/verbs.csv` is retained solely as a historical seed/legacy import format. Current coverage is documented in `data/CONTENT.md`.

## Multiple meanings and sentence variants

A word can have one or several exercises. Reuse its `word_id` and `infinitive`, but give every sentence its own stable, globally unique `sentence_id`. An optional `meaning` field holds a short Italian label for the sense illustrated by that sentence. It appears only after revealing the answer, not as a hint before guessing.

A single sentence is enough for a word with one meaning. Add variants only when useful, especially for distinct meanings. Supporting variants does not automatically create or generate them.

Random practice shuffles **words**, not individual sentences: each word appears once per round regardless of how many examples it has. On later visits, its sentences rotate in shuffled order, covering every variant before repeating. Guess history identifies both the word and the exact sentence, and includes the meaning label when present. Old content and logs remain compatible.

## Directly authored content (offline)

The canonical vocabulary is in `data/vocabulary.json`. Directly authored Italian/German sentence pairs are in `data/authored*.tsv`; their target words use `**bold markers**`. Import them without API calls:

```sh
uv run python scripts/import_authored.py data/authored*.tsv
```

For new batches, use TSV columns `word_id`, `italian`, `german`, and optional `sentence_id`, `meaning`. The importer gets the canonical infinitive from the vocabulary list, validates every link, preserves existing exercises, and saves atomically. Sentence IDs default to `word_id-01`; supply a fresh ID for each additional sense. Legacy `rank` columns and `--verbs PATH.csv` are still supported, but not required for new words. Existing sentence IDs cannot be overwritten with different content. Draft batches under `data/drafts/` are not included by the command above. See `data/CONTENT.md` for coverage, provenance, and unresolved source entries. The earlier API generation job is stopped; generating more content is not automatic.

## Optional API generation with gpt-6-luna

Put your key in `.env` (ignored by Git):

```dotenv
OPENAI_API_KEY=your-key
```

Then:

```sh
uv run deutsch generate --count 50
```

This makes **billable API calls**, explicitly using `gpt-6-luna` via the OpenAI Responses API. The model is not silently substituted if unavailable. The generator reads the first N entries of the local canonical vocabulary list and creates Italian/German sentence pairs in batches of 10. It does not re-fetch the historical CSV or lose newly added words. Entries marked with `review_note` are reported and left for lexical review. Structured output and local validation check IDs and highlighted substrings; they do not guarantee linguistic correctness. Review/edit cached content as needed.

Each completed batch is saved atomically. Re-running skips existing word IDs and preserves all their sentence variants, allowing interrupted generation to resume or the deck to grow. This optional command still creates only a first sentence for missing words; it does not automatically expand senses. To regenerate from scratch without overwriting an existing deck:

```sh
uv run deutsch generate --count 50 --output data/new-exercises.json
uv run deutsch play --data data/new-exercises.json
```

Custom decks can supply `--vocabulary PATH.json` to `play`, `recommend`, `build-frequencies`, `check-vocabulary`, `generate`, and the importer. For adaptive practice, also build/pass a matching `--frequencies PATH.json`. Every imported sentence must refer to a word in its catalog; adding an entry with no sentences does not block practice on the already covered words.

The original [source ranking](https://gist.github.com/wanderingstan/7eaaf0e22461b505c749e268c0b72bc4#file-top-german-verbs-csv) has quirks: for example, the rare verb `einen` is ranked third. V0 preserves the supplied list rather than silently replacing entries. Synonyms are not accepted automatically; answers are checked against the specific target infinitive.

## Flagging ambiguous sentences

After answering or revealing an exercise, use `/alternative` (or `/alt`) at the next prompt if you think the **previous** Italian sentence also permits another German word. A blue confirmation indicates that it was saved for review. Using the command again for the same presentation does not duplicate the flag. If there is no previous exercise in this session, it tells you and changes nothing.

Flags append to **`data/guesses.alternatives.jsonl`**, included in the private repository's log-versioning policy. Each record stores the previous sentence pair, canonical target, stable word/sentence IDs, and its presentation ID, so a later reviewer can find the corresponding guesses in the separate guess log. With a custom `--log PATH`, the default is `<stem>.alternatives.jsonl` beside it; override it with `play --alternative-log PATH`. Guess, event, and review logs must use distinct paths.

An alternative translation belongs to a **specific sentence (`sentence_id`)**, not the word globally. A valid alternative for one meaning/context must not be copied to other sentences using the same verb. Future review approvals must stay sentence-specific.

This only records a suspicion: it does **not** accept synonyms, forgive earlier mistakes, alter mastery, modify sentence content, or run any AI/API review automatically. Review/answer-policy changes are a separate step. Failed flag writes are visible and can be retried without counting as guesses.

## Guess history

Every submitted guess, including repeated attempts and whitespace-only input, appends a JSON object to `data/guesses.jsonl`. An empty line is the reveal command, not a guess. Raw input is preserved exactly. Records include:

- UTC timestamp, schema version, and session ID; new schema-v2 guesses also include a unique `presentation_id`
- Word ID, sentence ID, expected infinitive, and optional meaning label
- Exact `guess`, `result` (`correct`, `almost_there`, `incorrect`)
- Levenshtein distance, threshold, and attempt number for this presentation

Giving up is not a guess and does not add a guess record. Both practice modes now append separate **presentation events** to `data/guesses.events.jsonl`: prompt shown, completed, gave up, or abandoned. Guess records and events share the presentation ID, so retries cannot inflate mastery. Quitting/interrupting without a guess is not scored as failure. Logging errors are visible; failure to save a presentation event stops the session rather than silently continuing with incomplete history.

Keep the exercise file alongside the logs so IDs continue to identify the original prompts. History is append-only and never sent to OpenAI by practice or recommendations. **At the user's explicit request, project logs under `data/` are versioned in this private GitHub repository**, including guesses, presentation events, generation logs, and ambiguity flags when present. This is personal learning data, not anonymous content. Other JSONL files remain ignored by default; `.env` and credentials must never be committed. Practice itself does not upload or push anything. Use `--log PATH` to change the guess location; events default to `<log-stem>.events.jsonl` beside it, or set `--events PATH`. The paths must differ. Exported recommendation reports contain personal learning statistics too—keep them private.

Existing schema-v1 guess logs need no migration or rewrite. Adaptive mode conservatively groups legacy retries using sessions, sentence IDs, and attempt resets. Old reveals were never recorded and cannot be recovered; a missing first attempt is not inferred from a later successful retry. Adaptive selection is a lightweight heuristic, not a full spaced-repetition system. The session footer still counts successful guesses and total attempts; it is not the adaptive mastery estimate or a bonus-points system.

## Tests

```sh
uv run pytest -q
```

Tests cover answer normalization, edit distance, raw JSONL and presentation logging, legacy retry grouping, vocabulary/sense coverage, catalog validation, import atomicity, exercise variants, shuffled rounds, frequency extraction/provenance/fallbacks, adaptive weighting/cooldowns/new-word quotas, read-only offline reports, mocked API generation/resume validation, and inline terminal interactions (including reveal, retries, failed writes, plain output, and clean exits).
