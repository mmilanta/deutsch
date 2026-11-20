# Sentence difficulty snapshot

[`data/difficulty/ranking.tsv`](../data/difficulty/ranking.tsv) ranks all **2,911 exercises** in the deck snapshot. Use `sentence_id` to join the ranking to the exercise deck. `hardest_rank` starts at 1 and a higher `difficulty` score means harder. The scores are relative: they are not learner success probabilities, CEFR levels, or usage frequencies. The terminal game, local browser game, and static export use this ranking to present sentences from easy to hard by default, with unranked sentences at the end.

## How it was measured

GPT-6 Luna judged which of two specific target infinitives an Italian-speaking learner would be more likely to guess with retries. It saw each Italian cue, the German reference, the target verb, and the recognized synonyms; the simulated learner only saw the Italian cue. A recognized synonym allows another try without penalty but does not complete the exercise. The exact prompt and exercise-deck checksum are in [`run.json`](../data/difficulty/run.json). No practice history was sent to the model.

- **14,555 distinct pairings:** every sentence faced 10 different sentences, five times in each display position. There were 402 same-verb comparisons. The comparison graph connects the full deck.
- **728 reverse-order checks:** Luna selected the same sentence as easier in 557 cases (76.5%). It chose A in 8,476 of 14,555 primary comparisons (58.2%).
- **15,283 valid judgments**, with no failed requests. Reported token usage at the standard API prices puts the cost at **$0.54672**. The earlier batch was cancelled without completing any requests.

[`comparisons.tsv`](../data/difficulty/comparisons.tsv) stores only the sentence IDs and the A/B verdicts, not raw API responses. `easier` refers to the listed order; `easier_reversed` refers to the swapped order (`-` means no reverse check). The ranking fits a regularized Bradley–Terry model to the primary votes with a separate term for appearing first. Reverse votes are held out as a consistency check rather than counting those pairs twice.

For example, the `bestehen` sentence for *insistere* ranks 793rd hardest, while the one for *superare una prova* ranks 1,999th. Don't read too much into small score gaps: the rating is a model judgment, and it has not been validated against learner performance.

## Rebuild offline

From the project root, using the judged exercise snapshot:

```sh
uv run --offline python scripts/rank_difficulty.py > /tmp/deutsch-difficulty.tsv
cmp data/difficulty/ranking.tsv /tmp/deutsch-difficulty.tsv
```

This reuses the stored judgments; it makes no API calls and needs no credentials. For a changed exercise deck, existing ranks remain a historical snapshot rather than an automatically updated difficulty estimate.
