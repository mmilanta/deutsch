# Content format

Paths below are relative to the project root, four levels above this `references/` directory. The application currently teaches **verbs**, so canonical answers are infinitives. Adding other parts of speech requires a separate application change; do not put nouns into the infinitive list as if they were verbs.

## Canonical vocabulary: `data/vocabulary.json`

A JSON array. Each record has:

- `word_id`: stable unique ID, lowercase ASCII letters, digits, hyphens, or underscores. It must start with a letter or digit. It need not be a source rank.
- `infinitive`: the German infinitive, using standard `ß` orthography and no surrounding whitespace.
- `meanings` (optional): distinct, nonempty Italian labels for the senses that need coverage. Omit when one ordinary example is enough.
- `review_note` (optional): an unresolved lexical issue. Never automatically clear it or invent an example to work around it.

New words belong here. Existing `verb-RANK` IDs are retained for history compatibility; new IDs can instead be mnemonic. Do not renumber existing words. Different IDs for the same infinitive may be historical duplicates; do not silently merge them because guess history refers to their original IDs.

Adding a meaning label declares a new coverage requirement; it does not retroactively label old exercises. Ask before changing the semantics of a historical sentence.

## Sentence batches: `data/authored-*.tsv`

UTF-8 tab-separated values. Recommended header:

```text
word_id	italian	german	sentence_id	meaning
```

Columns:

- `word_id`: exactly an ID from the canonical list.
- `italian`: complete Italian sentence with exactly one `**highlighted target**`.
- `german`: complete German translation with exactly one `**highlighted target**`.
- `sentence_id` (optional): globally unique stable ID; defaults to `word_id + '-01'`. Always provide it when adding another sense or variant.
- `meaning` (optional): Italian sense label. If the word declares required `meanings`, use an exact label from that list. A blank cell means no label.
- `frame` (optional): `full` by default. `can`, `want`, and `need` expand explicitly authored verb phrases into matching modal sentences; they do not generate or translate content. Prefer full, natural sentence pairs for new work.

Literal tab/newline characters within a sentence must be correctly CSV-quoted; it is simpler to avoid them. Markers are stripped on import and the exact target substrings are stored separately.

Legacy batches can use `rank` instead of `word_id`; a rank maps to `verb-RANK`. Numeric ranks and `verbs.csv` are not required for new vocabulary. `--verbs PATH.csv` remains a compatibility alias for the importer's `--vocabulary` option.

## Imported exercises: `data/exercises.json`

A flat JSON array, preserving compatibility with the current application:

- `word_id`: links to the canonical vocabulary.
- `sentence_id`: identifies this particular sentence pair.
- `infinitive`: canonical expected answer, obtained from the vocabulary list by the importer.
- `italian`, `italian_target`: plain sentence and exact highlighted substring.
- `german`, `german_target`: plain sentence and exact highlighted substring.
- `meaning` (optional): the illustrated sense.

Several entries can share `word_id`, but not `sentence_id`. The app visits each word once per shuffled round and rotates through its variants. It reveals the meaning label only after the guess/reveal, not as a hint.

Do not overwrite existing sentence IDs with different text or meaning. If a historical exercise needs correction, treat it as a separate, explicit maintenance task rather than silently repurposing an ID referenced in logs.

## Coverage report

`uv run deutsch check-vocabulary --json` returns:

- `vocabulary_count`, `sentence_count`, `covered_word_count`.
- `missing_words`: full canonical entries with no valid linked sentence.
- `missing_meanings`: required labels that lack corresponding sentences.
- `errors`: orphan word references, mismatched canonical answers, duplicate IDs, or undeclared meaning labels.

An entry with `review_note` remains visible as missing, not silently treated as covered. Resolve or report it explicitly. Parse/validation errors also produce a nonzero exit status. The check performs no writes and calls no API.
