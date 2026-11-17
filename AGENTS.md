# Deutsch project

- `data/vocabulary.json` is the canonical vocabulary list. `data/exercises.json` contains its linked Italian/German sentence pairs; preserve stable word/sentence IDs and `data/guesses.jsonl`.
- For vocabulary additions, coverage checks, or missing sentence pairs, read `.agents/skills/complete-vocabulary/SKILL.md` and follow it. Respect requests for check-only work or no new sentences.
- Author content directly unless the user explicitly authorizes a model API workflow. Never read or expose `.env` to perform a coverage audit; never silently start paid/background generation.
- The TUI stays minimal and inline. Retain `ß` in displayed German, accept `ss` too, and keep exact raw guesses in the log.
- Frequency estimates live separately in `data/frequencies.json`; see `docs/adaptive.md` and `data/FREQUENCIES.md`. Practice/recommendations must stay offline. Only the explicit `build-frequencies` command downloads public corpus data; `wordfreq` is an optional build dependency, not a runtime requirement.
- Keep guesses, presentation events, and ambiguity flags append-only. The user explicitly requested versioning project logs under `data/` in this private repository; do not upload them elsewhere without permission, and never commit `.env` or credentials. Tests and simulations must use temporary paths and must not append to the user's history. Richer grammar/partial-credit practice is a future TODO only (`TODO.md`).
- Alternative translations are properties of a specific exercise (`sentence_id`), never globally of a vocabulary word. `/alternative` and `/alt` flag the previous completed/revealed sentence only. Future review approvals must not propagate to other sentences, even for the same word or meaning.
- Verify with `uv run deutsch check-vocabulary` (exit 1 means incomplete coverage) and `uv run pytest -q`.
