# TODO

## Next planned expansion: vocabulary beyond verbs

**Planning only — no vocabulary or exercises added yet.**

### Scope and priorities

- Keep **verbs** and expand into **nouns, adjectives, and adverbs**.
- Suggested order: common everyday nouns and adjectives first, then useful adverbs of time, place, frequency, and manner. Continue filling useful verb gaps alongside them.
- Prefer broadly useful everyday vocabulary over rare technical words, proper names, or exhaustive grammatical categories.
- **Connectors/conjunctions are low priority**, not a target of the initial expansion. Do not let frequent discourse/linking words dominate the adverb list just because a corpus labels them ADV.
- Optionally add useful fixed expressions and short lexical phrases later. These are vocabulary units, not another part of speech; do not expand into a full grammar syllabus by default.
- In German, an adjective can also be used adverbially without changing form. Represent relevant uses/meanings without automatically creating duplicate vocabulary entries for the same lexical item.

### Changes required before importing content

1. Generalize the catalog/exercise model from a required `infinitive` to a **lemma/base form and part of speech**, with backward compatibility for existing verb data. Preserve all existing word IDs, sentence IDs, and history; do not rebuild or renumber the catalog.
2. Define the expected base answer by category: verb infinitive, noun singular dictionary form where applicable, adjective positive form, and adverb dictionary form. Handle plural-only nouns explicitly. Keep standard German capitalization/spelling in displayed content.
3. Make prompt instructions and reveal labels category-aware: do not ask for an infinitive when practising a noun or adjective. Retain Italian sentence prompts, bold targets, and the minimal inline UI.
4. Extend frequency extraction to the appropriate lemma/POS categories. Distinguish homographs across categories, exclude proper names from the initial noun pool, and keep source/confidence metadata. Reuse frequency × need selection rather than reverting to random vocabulary dumps.
5. Curate common, useful words and their intended meanings, then add linked Italian/German sentence exercises. One sentence per meaning is sufficient; do not create variants merely to increase counts. Respect the current pause on adding sentences until content expansion is explicitly requested.
6. Test old verb decks/history unchanged alongside mixed-category decks, answer checking, frequency selection, and coverage auditing.

The grammatical forms and bonus-point mechanics below remain a **separate future feature**. Expanding the word classes does not itself authorize implementing those mechanics, paid generation, or automatic content imports.

## Future: richer word knowledge and partial-credit scoring

**Documented only — do not implement yet.** This is a future extension after the frequency/knowledge-based word selector.

Support additional grammatical information for each vocabulary item:

- **Nouns:** article/gender (`der`, `die`, `das`) and plural. Store the full plural form as well as its ending/pattern where useful, because umlauts and irregular forms cannot always be represented by an ending alone.
- **Verbs:** third-person singular present, Präteritum, and Perfekt. Store the past participle plus the auxiliary (`haben` or `sein`); ideally show the complete third-person forms so the expected answer is unambiguous.
- **Adjectives:** comparative and superlative, including irregular forms. These are the usual useful principal forms. Handle adjectives without an ordinary comparison explicitly; adjective declension can be a separate, later exercise type rather than required by default.

### Practice and scoring

- Correctly recalling the original vocabulary word still earns base points, even when the extra grammatical information is missing or wrong.
- Award additional points for correct grammatical fields, with the highest score for getting everything right.
- Choose the exact point values and input interaction when implementing; do not treat missing optional fields as a completely wrong vocabulary answer.
- Distinguish lexical knowledge from grammatical knowledge in history and recommendations: someone can know a noun but not its article, or know a verb but not its past forms.
- Preserve the minimal inline UI, existing exercise IDs/history, exact raw guesses, and acceptance of both `ß` and Swiss `ss` spellings.

This will require extending the current verb-only vocabulary model and agreeing on the answer format before adding noun/adjective content. No new grammar fields, prompts, or scoring rules are introduced by this TODO.
