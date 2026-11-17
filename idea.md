# Idea

A tool for learning German vocabulary through Italian example sentences. A terminal UI should be sufficient for v0; a website is not required. Use terminal bold formatting to highlight words.

## Terminal UI

Keep the UI minimal and inline, like an ordinary terminal conversation—not a full-screen terminal window.

- No alternate screen, panels, buttons, borders, dashboard, or screen clearing.
- Leave previous prompts, guesses, and translations in terminal scrollback.
- Use bold for target words and subtle colors for feedback, with readable text labels and a no-color fallback.
- Show a simple `> ` answer prompt. Enter submits a guess; an empty line reveals the answer; `/q` quits.
- After revealing a translation, print the next exercise below it.
- Persist guesses in the existing JSONL file across runs.

## V0 learning loop

- Show an Italian sentence with the target word highlighted.
- Ask the user for the German verb in the infinitive, regardless of its conjugation in the sentence. For example, “Io **vado** a casa” expects `gehen`, not `gehe`.
- When revealing the answer, show the full German sentence with the target verb in bold, rather than revealing the word alone. For example: “Voglio **andare** a casa” → “Ich möchte nach Hause **gehen**.” If the translation uses a conjugated form, bold that form and also show the expected infinitive.
- Allow the user to give up and reveal the answer.
- Use Levenshtein distance to distinguish near misses: an exact match is correct; a non-exact match within a small edit-distance threshold gets “Almost there”; other guesses are incorrect. Near misses are not counted as correct, and the user can try again. Start with a threshold of 1 edit, configurable later. Compare trimmed, lowercased input, but preserve the exact raw input in the log.

## Content structure and maintenance

- Keep a canonical vocabulary list in `data/vocabulary.json`, separate from the sentence pairs in `data/exercises.json`.
- Each vocabulary entry has a stable word ID and its German infinitive (v0 focuses on verbs). Each sentence pair refers to that word ID and has its own sentence ID.
- Add words to the canonical list; numeric source ranks are not required for new entries. Keep the original CSV only as a historical source snapshot.
- Provide a read-only coverage command that reports words without sentences, missing declared meanings, and invalid links.
- Provide a project skill (`complete-vocabulary`) that checks coverage and authors/imports missing Italian/German sentence pairs directly, without an external model API. Do not overwrite old sentences or guess history.
- If a user requests only a check or no new sentences, the skill must not create content. Flag uncertain entries rather than inventing meanings.
- This change installs the structure and workflow only; it does not generate or import new sentences now.

## Multiple sentences and meanings

- Allow several sentences per vocabulary word, especially to illustrate distinct German meanings.
- One sentence is sufficient if a word has only one meaning; do not add variants just to increase the count.
- Keep the same word ID and expected infinitive across variants. Assign each sentence a unique, stable sentence ID.
- Optionally store an Italian meaning label per sentence, shown only when revealing the answer.
- Select words evenly in shuffled rounds, and rotate a word's sentences across visits so words with more meanings do not crowd out other words.
- Preserve all sentence variants during import and optional API generation. Guess records must identify the specific sentence and, if available, its meaning.
- For now, implement support only: do not create or import additional sentences for this feature.

## Guess collection

Store every guess as a new record in a JSONL file, including:

- Timestamp.
- Word ID and sentence ID, linking to the exercise shown.
- Expected German infinitive.
- Exactly what the user typed, preserving the raw input even if answer checking normalizes it.
- Result of the guess (`correct`, `almost_there`, or `incorrect`).
- Levenshtein distance between the normalized guess and the expected infinitive.

For v0, only collect this history; do not implement personalized recommendations yet. In the future, use it to recommend which words to practice.

## German orthography

Display standard German spelling, retaining `ß` where appropriate (for example, `heißen`, `weiß`, `Straße`). Accept both `ß` and Swiss `ss` spellings as correct during answer checking (`heißen` and `heissen`), while preserving raw guesses exactly in the log.

## Initial content

Start with the verbs from https://gist.github.com/wanderingstan/7eaaf0e22461b505c749e268c0b72bc4#file-top-german-verbs-csv.

The initial vocabulary came from the linked CSV. Direct authoring through the project skill is the current workflow; `gpt-6-luna` remains an explicitly invoked, optional API generator, never the default for completing vocabulary.