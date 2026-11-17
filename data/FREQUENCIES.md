# Frequency metadata: provenance, limitations, and licensing

`frequencies.json` is a derived, non-personal data artifact for adaptive scheduling, separate from canonical `vocabulary.json` and sentence content. It includes source/version URLs, input SHA-256 checksums, attribution, and the lookup method/count for every canonical word. It is safe to share without sharing learning history.

## Primary source: UD German GSD

- Repository/release: [UniversalDependencies/UD_German-GSD, r2.16](https://github.com/UniversalDependencies/UD_German-GSD/tree/r2.16).
- Source files: `de_gsd-ud-train.conllu`, `de_gsd-ud-dev.conllu`, `de_gsd-ud-test.conllu`.
- [Upstream README, attribution, methodology, and terms](https://github.com/UniversalDependencies/UD_German-GSD/blob/r2.16/README.md).
- Citation: Ryan McDonald et al. (2013), **Universal Dependency Annotation for Multilingual Parsing**, Proceedings of ACL 2013.
- UD contributors: Slav Petrov, Wolfgang Seeker, Ryan McDonald, Joakim Nivre, Dan Zeman, Adriane Boyd, Verena Blaschke.
- Original treebank contributors credited upstream: Yvonne Quirmbach-Brundage, Amy LaMontagne, Milan Souček, Timo Järvinen, Alessandra Radici.
- Annotation license: Google released the annotations under **Creative Commons Attribution-ShareAlike 4.0** ([license](https://creativecommons.org/licenses/by-sa/4.0/)). The upstream README distinguishes annotation licensing from rights in the underlying sentence texts; consult those terms when downloading/using the corpus itself.

Adaptations made here: count only VERB/AUX lemmas; restore annotated separable particles; count word tokens excluding PUNCT/SYM; convert rates to Zipf scores; map the resulting estimates to this project's canonical vocabulary IDs. All three splits contribute counts; no model is trained or evaluated. The artifact redistributes aggregate counts/scores, **not corpus sentences or full corpus files**.

The initial build contains 254,167 corpus word tokens and verb-lemma evidence for 1,660 of the 2,897 catalog entries. These are corpus-specific estimates, not a representative census of German usage. Genres include news, reviews, and web/Wikipedia. Lemmas are automatically annotated and may be wrong. Small counts are weak evidence; particles, unusual spellings, and constructions may be missed. Annotation release date is not the date all texts were written.

## Provisional fallback: wordfreq

- [wordfreq](https://github.com/rspeer/wordfreq), by **Robyn Speer**, installed version recorded in the artifact (initial build: 3.1.1).
- Requested upstream citation: Robyn Speer (2022), **rspeer/wordfreq: v3.0 (v3.0.2)**, Zenodo, [doi:10.5281/zenodo.7199437](https://doi.org/10.5281/zenodo.7199437).
- Code: Apache license; bundled frequency data may be redistributed under **CC BY-SA 4.0**, with upstream attribution conditions. See the [wordfreq license/credits](https://github.com/rspeer/wordfreq#license).
- Underlying sources credited upstream include Google Books Ngrams, the Leeds Internet Corpus, Wikipedia contributors, ParaCrawl, OPUS OpenSubtitles 2018 and OpenSubtitles, and SUBTLEX.
- **SUBTLEX is freely available data**, created by Marc Brysbaert and collaborators: [source lists](http://crr.ugent.be/programs-data/subtitle-frequencies).
- SUBTLEX-US: Brysbaert & New (2009); SUBTLEX-UK: van Heuven, Mandera, Keuleers & Brysbaert (2014); SUBTLEX-CH: Cai & Brysbaert (2010); SUBTLEX-NL: Keuleers, Brysbaert & New (2010).
- German citation: M. Brysbaert, M. Buchmeier, M. Conrad, A. M. Jacobs, J. Bölte, & A. Böhl (2011). **The word frequency effect: A review of recent developments and implications for the choice of frequency estimates in German.** Experimental Psychology, 58, 412–424.

The `wordfreq` snapshot reflects language use through approximately 2021. Lookups are made using its official German `zipf_frequency` API, not by copying an internal raw word list. Surface frequency is not verb-lemma frequency: `einen`, for example, is commonly an article. Therefore, for words absent from the lemma/POS corpus, cap the fallback at Zipf 2.5 and label it `surface_fallback`; preserve the uncapped surface lookup for inspection. Initial build: 1,233 fallback entries, four with no frequency evidence at all. Missing evidence does not establish rarity, and the cap is a conservative scheduling policy, not a measured frequency correction.

## Derived-data license

The derived frequency data in **`frequencies.json`** are distributed under **CC BY-SA 4.0** ([legal code](https://creativecommons.org/licenses/by-sa/4.0/legalcode)), preserving the above credits and indicating the adaptations. Attribution and source/license metadata are also embedded in the JSON so they travel with the data. Keep them when redistributing or adapting it; do not export an attribution-free frequency table. No upstream endorsement is implied.

This data notice does not relicense the application's code, canonical catalog, or sentence content. Raw downloaded corpus files remain in ignored `.cache/deutsch-frequency/`, subject to their upstream terms.

## Rebuild

```sh
uv run --extra frequency deutsch build-frequencies
```

The explicit build command downloads the three fixed-release corpus files if absent (~22 MB), uses local `wordfreq`, and atomically replaces only the requested frequency artifact. It does not read guesses, `.env`, or model credentials, and it makes no paid/model API calls. Cached rebuilds need no network. Practice and recommendations never download anything.

After intentional vocabulary changes, rebuild to refresh coverage, or pass a custom artifact with `--frequencies PATH`. A changed/missing word-ID/infinitive mapping gets conservative minimum weight until rebuilt. For scoring formulas and history behavior, see [`docs/adaptive.md`](../docs/adaptive.md).
