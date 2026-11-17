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

After a correct answer or a reveal, the next exercise is printed below. Nothing is cleared or redrawn.

Correct guesses automatically reveal the translation, with the German verb in **bold** and the expected infinitive underneath. A one-edit near miss gets **Almost there**; near misses and wrong answers allow another attempt without revealing the answer. Insertion, deletion, and substitution each count as one edit; a transposition usually counts as two.

German content retains **standard German spelling**, including `ß` (`heißen`, `weiß`, `Straße`). Both `ss` and `ß` spellings are accepted as correct when checking answers (`heissen` and `heißen`); raw guesses are still logged unchanged.

Checking ignores leading/trailing whitespace and capitalization, normalizes Unicode, and keeps German umlauts significant (`konnen` is a near miss for `können`, not correct). Set `--threshold 0` to disable near misses, or increase it:

```sh
uv run deutsch play --threshold 1
NO_COLOR=1 uv run deutsch
```

Use a terminal supporting bold and Unicode for the best experience. Output uses your normal terminal background and scrollback; feedback also has text labels for monochrome use.

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

Practice shuffles **words**, not individual sentences: each word appears once per round regardless of how many examples it has. On later visits, its sentences rotate in shuffled order, covering every variant before repeating. Guess history identifies both the word and the exact sentence, and includes the meaning label when present. Old content and logs remain compatible.

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

Custom decks can supply `--vocabulary PATH.json` to `play`, `check-vocabulary`, `generate`, and the importer. Every imported sentence must refer to a word in its catalog; adding an entry with no sentences does not block practice on the already covered words.

The original [source ranking](https://gist.github.com/wanderingstan/7eaaf0e22461b505c749e268c0b72bc4#file-top-german-verbs-csv) has quirks: for example, the rare verb `einen` is ranked third. V0 preserves the supplied list rather than silently replacing entries. Synonyms are not accepted automatically; answers are checked against the specific target infinitive.

## Guess history

Every submitted guess, including repeated attempts and whitespace-only input, appends a JSON object to `data/guesses.jsonl`. An empty line is the reveal command, not a guess. Raw input is preserved exactly. Records include:

- UTC timestamp, schema version, and session ID
- Word ID, sentence ID, expected infinitive, and optional meaning label
- Exact `guess`, `result` (`correct`, `almost_there`, `incorrect`)
- Levenshtein distance, threshold, and attempt number for this presentation

Giving up is not a guess and does not add a guess record. Logging errors are shown rather than silently losing a guess. Keep the exercise file alongside the log so IDs continue to identify the original prompts. The log is local and ignored by Git; guesses are not sent to OpenAI. Use `--log PATH` to change its location.

V0 uses shuffled word rounds without immediate word repeats at round boundaries (when multiple words exist), rotating sentence variants across visits. It collects history but does **not** implement recommendations or spaced repetition yet.

## Tests

```sh
uv run pytest -q
```

Tests cover answer normalization, edit distance, raw JSONL logging, vocabulary/sense coverage, catalog validation, import atomicity, exercise variants, shuffled rounds, mocked API generation/resume validation, and inline terminal interactions (including reveal, retries, failed writes, plain output, and clean exits).
