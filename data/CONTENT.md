# Vocabulary and exercise coverage

`vocabulary.json` is the canonical vocabulary list. It was initialized from the 2,897-row snapshot in `verbs.csv`, retaining all original word IDs and adding review notes for known questionable entries. New words and required meaning labels belong in the JSON list, not the CSV. The CSV remains a historical seed; do not recreate the JSON from it and overwrite later additions.

The complete source list was read before the directly authored batches were written. Coverage can now be checked offline with `uv run deutsch check-vocabulary` or its `--json` report. The `complete-vocabulary` project skill documents the audit/author/import workflow. Installing the catalog and skill did not add sentences or modify guess history.

## Current content

- Ranks 1–710: previously generated using `gpt-6-luna`.
- Ranks 711–1,000: 290 sentence pairs written directly by the coding assistant in `authored-exercises.tsv`.
- Ranks 1,001–1,200, except 1,058 and 1,145: 198 sentence pairs written directly by the coding assistant in `authored-1001-1200.tsv`.
- Ranks 1,201–2,100, except 1,288, 1,623, 1,684, 1,990, 2,000, and 2,006, plus the resolved entries 1,058 and 1,145: 896 further sentence pairs written directly by the coding assistant in `authored-1201-1500.tsv`, `authored-1501-1800.tsv`, and `authored-1801-2100.tsv`.
- The first 300 entries were reviewed for common meanings and ambiguous prompts. `authored-0001-0300-senses.tsv` adds 338 labelled examples; 215 of the first 300 verbs now have multiple examples. The deck has 450 prompts in this range with curated, sentence-specific alternative answers (on original prompts these are stored directly in `exercises.json`). Existing example text and IDs were preserved. The added meaning labels are coverage requirements for the new senses, not retroactive labels for the historical prompts. This is a teaching set, not a complete dictionary inventory.
- The same review for ranks 301–1,000 adds 479 labelled examples across 365 verbs in `authored-0301-0500-senses.tsv`, `authored-0501-0700-senses.tsv`, and `authored-0701-1000-senses.tsv`. In this range, 954 prompts have reviewed alternative answers (591 original and 363 new). Original sentence text and IDs were preserved. The historical rank 411 rain prompt uses the form `regnet` with canonical `regen`; it now accepts `regnen` too. The new `regen` prompt illustrates `sich regen` (to stir or move slightly).
- Total: **2,911 exercises covering 2,094 source entries**, with **803 source entries still missing imported exercises**.
- Another 596 draft pairs for ranks 2,101–2,700 were written before the request to pause adding sentences. They remain under `drafts/`, require review, and have **not** been imported. The normal `data/authored*.tsv` glob does not include them.

Direct authorship here means content produced in the coding session, not a claim of human review. No OpenAI API calls were made to produce or import the directly authored batches. These sentences are structurally validated but would still benefit from linguistic review. Modal constructions are frequent because the learner supplies an infinitive; some sentences instead show conjugated forms.

The old API generation job is stopped. There is no background process filling the remaining entries.

## Source caveats

This is a frequency-derived list, not a curated beginner syllabus. It includes vulgar words, historical or regional usages, rare technical verbs, and words whose apparent frequency comes from common non-verb homographs. Keep these distinctions in mind when expanding or curating the deck.

The following entries need additional lexical review rather than an invented exercise:

- 1,288 `firmen`, 1,623 `verborgen`, 1,684 `schlagzeilen`, 1,990 `flügeln`, 2,000 `gutachten`, and 2,006 `buben`: verify the intended rare verb senses before importing exercises.
- 2,623 `seilen`, 2,632 `fotzen`, and 2,693 `ärschen`: likewise need lexical review; not included in the draft pairs.
- 2,571 `entflohen`: this is the past participle of `entfliehen`, already present at rank 1,581, rather than the infinitive expected by the app.

The formerly unresolved `socken` and `nummern` were checked in German Wiktionary: [socken](https://de.wiktionary.org/wiki/socken) can mean walking/running colloquially, and [nummern](https://de.wiktionary.org/wiki/nummern) means numbering. Their examples were authored directly, not copied from the dictionary. The source also contains dated, vulgar, and potentially offensive terms, including `türken`; a curated beginner deck should label or filter these separately.

Other questionable-looking entries in the remaining list should be checked individually; they are not automatically corrected or excluded. In particular, some have legitimate rare verb senses despite being much more familiar as nouns or adjectives.

## Import directly authored batches

Each new TSV row contains a `word_id` from `vocabulary.json`, an Italian sentence, and a German sentence. Old batches can still use a numeric `rank`, mapped to `verb-RANK`. Mark exactly one target in each sentence with `**double asterisks**`.

Optional columns:

- `sentence_id`: a stable, globally unique ID. Defaults to `verb-RANK-01`; use a different ID for each additional sentence of the same word.
- `meaning`: an Italian label for the particular sense, shown only after revealing the answer.
- `accepted_infinitives`: semicolon-separated German answers that also fit this exact Italian prompt. Do not repeat the canonical answer. Use a German base form (including a reflexive pronoun where appropriate). These answers score as correct; review flags do not automatically add to this list.
- `frame`: defaults to `full` for complete sentences. `can`, `want`, and `need` expand explicitly authored verb phrases into matching short Italian/German modal sentences. These frames do not generate or translate content.

Multiple sentences share a word ID and infinitive. Existing one-sentence rows remain valid.

```sh
uv run python scripts/import_authored.py data/authored*.tsv
```

This is offline. It obtains the canonical infinitive from `vocabulary.json`, preserves standard German spelling including `ß`, validates target substrings, IDs, and declared meaning labels, and atomically updates `exercises.json`. The `--verbs PATH.csv` option remains a compatibility alias for importing against the historical format. Re-importing identical rows is harmless. Conflicting existing exercises are rejected so sentence IDs referenced by guess history are not silently repurposed.
