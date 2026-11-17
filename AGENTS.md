# Deutsch project

- `data/vocabulary.json` is the canonical vocabulary list. `data/exercises.json` contains its linked Italian/German sentence pairs; preserve stable word/sentence IDs and `data/guesses.jsonl`.
- For vocabulary additions, coverage checks, or missing sentence pairs, read `.agents/skills/complete-vocabulary/SKILL.md` and follow it. Respect requests for check-only work or no new sentences.
- Author content directly unless the user explicitly authorizes a model API workflow. Never read or expose `.env` to perform a coverage audit; never silently start paid/background generation.
- The TUI stays minimal and inline. Retain `ß` in displayed German, accept `ss` too, and keep exact raw guesses in the log.
- Verify with `uv run deutsch check-vocabulary` (exit 1 means incomplete coverage) and `uv run pytest -q`.
