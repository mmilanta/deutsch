"""Reproducible, offline-at-runtime frequency estimates with explicit provenance."""
from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from deutsch.vocabulary import VocabularyEntry

UD_RELEASE = "r2.16"
UD_BASE = f"https://raw.githubusercontent.com/UniversalDependencies/UD_German-GSD/{UD_RELEASE}"
UD_FILES = [f"de_gsd-ud-{split}.conllu" for split in ("train", "dev", "test")]
FALLBACK_CAP = 2.5


def lemma_key(text: str) -> str:
    # Unlike answer checking, do not conflate genuinely different ss/ß lemmas.
    return unicodedata.normalize("NFC", text).lower()


class Frequency(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    infinitive: str
    zipf: float = Field(ge=0, le=9)
    method: Literal["lemma_pos", "surface_fallback", "missing"]
    corpus_count: int = Field(default=0, ge=0)
    surface_zipf: float | None = Field(default=None, ge=0, le=9)

    @property
    def commonness(self) -> float:
        return 0.1 + 0.9 * min(1.0, max(0.0, (self.zipf - 2.0) / 4.0))


class FrequencyTable(BaseModel):
    schema_version: int = 1
    data_license: str = "CC BY-SA 4.0"
    data_license_url: str = "https://creativecommons.org/licenses/by-sa/4.0/"
    built_at: str
    corpus_tokens: int = Field(ge=0)
    sources: list[dict]
    methodology: str
    words: dict[str, Frequency]

    def for_word(self, word_id: str, infinitive: str) -> Frequency:
        item = self.words.get(word_id)
        if item is not None and item.infinitive == infinitive:
            return item
        return Frequency(infinitive=infinitive, zipf=0, method="missing")


def load_frequencies(path: Path) -> FrequencyTable:
    table = FrequencyTable.model_validate_json(path.read_text(encoding="utf-8"))
    if table.schema_version != 1:
        raise ValueError(f"Unsupported frequency schema: {table.schema_version}")
    return table


def count_corpus(paths: list[Path]) -> tuple[Counter[str], int]:
    """Count VERB/AUX lemmas, not homographic determiners/nouns or raw infinitives."""
    counts: Counter[str] = Counter()
    tokens = 0
    for path in paths:
        sentence: list[list[str]] = []

        def consume() -> None:
            nonlocal tokens
            particles: dict[str, list[tuple[int, str]]] = {}
            for row in sentence:
                if row[7] == "compound:prt":
                    particles.setdefault(row[6], []).append((int(row[0]), row[1]))
            for row in sentence:
                if row[3] not in {"PUNCT", "SYM"}:
                    tokens += 1
                if row[3] not in {"VERB", "AUX"} or row[2] == "_" or "|" in row[2]:
                    continue
                lemma = lemma_key(row[2])
                prefix = "".join(lemma_key(text) for _, text in sorted(particles.get(row[0], [])))
                if prefix and not lemma.startswith(prefix):
                    lemma = prefix + lemma
                counts[lemma] += 1
            sentence.clear()

        with path.open(encoding="utf-8") as file:
            for number, line in enumerate(file, 1):
                line = line.rstrip("\n")
                if not line.strip():
                    consume()
                elif not line.startswith("#"):
                    row = line.split("\t")
                    if len(row) != 10:
                        raise ValueError(f"Invalid CoNLL-U row at {path}:{number}")
                    if row[0].isdigit():  # Ignore multiword-token wrappers and empty nodes.
                        sentence.append(row)
            consume()
    if not tokens:
        raise ValueError("The frequency corpus contains no word tokens")
    return counts, tokens


def estimate_frequencies(entries: list[VocabularyEntry], counts: Counter[str], tokens: int,
                         surface_lookup) -> dict[str, Frequency]:
    words = {}
    for entry in entries:
        count = counts[lemma_key(entry.infinitive)]
        surface = float(surface_lookup(entry.infinitive))
        if count:
            score, method = math.log10(count / tokens * 1_000_000_000), "lemma_pos"
        else:
            # A high surface frequency can be an article/noun, e.g. 'einen'.
            # Lack of corpus evidence is uncertainty, not proof a verb is rare.
            score = min(FALLBACK_CAP, surface)
            method = "surface_fallback" if surface > 0 else "missing"
        words[entry.word_id] = Frequency(
            infinitive=entry.infinitive, zipf=round(max(0, score), 3), method=method,
            corpus_count=count, surface_zipf=surface,
        )
    return words


def build_frequencies(entries: list[VocabularyEntry], output: Path,
                      cache: Path = Path(".cache/deutsch-frequency")) -> FrequencyTable:
    try:
        from wordfreq import zipf_frequency
    except ImportError as error:
        raise ValueError("Install frequency tools: uv sync --extra frequency") from error
    cache.mkdir(parents=True, exist_ok=True)
    sources = []
    paths = []
    for filename in UD_FILES:
        path = cache / filename
        url = f"{UD_BASE}/{filename}"
        if not path.exists():
            print(f"Downloading {filename} (one-time public corpus download)…", flush=True)
            request = Request(url, headers={"User-Agent": "DeutschVocabulary/0.1"})
            with urlopen(request, timeout=90) as response:
                data = response.read()
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
        paths.append(path)
        sources.append({"name": f"UD German GSD {UD_RELEASE}: {filename}", "url": url,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                        "attribution": "Google and UD German GSD contributors: Slav Petrov, Wolfgang Seeker, Ryan McDonald, Joakim Nivre, Dan Zeman, Adriane Boyd, Verena Blaschke; original treebank contributors Yvonne Quirmbach-Brundage, Amy LaMontagne, Milan Souček, Timo Järvinen, Alessandra Radici",
                        "citation": "McDonald et al. (2013), Universal Dependency Annotation for Multilingual Parsing, ACL 2013",
                        "source_notes": f"{UD_BASE}/README.md"})
    counts, tokens = count_corpus(paths)
    words = estimate_frequencies(entries, counts, tokens, lambda word: zipf_frequency(word, "de"))
    sources.append({"name": f"wordfreq {version('wordfreq')}", "url": "https://github.com/rspeer/wordfreq",
                    "citation": "Robyn Speer (2022), wordfreq; https://doi.org/10.5281/zenodo.7199437",
                    "data_license": "CC BY-SA 4.0; includes freely available SUBTLEX data",
                    "subtlex_credit": "Freely available SUBTLEX data: US, Brysbaert & New (2009); UK, van Heuven, Mandera, Keuleers & Brysbaert (2014); CH, Cai & Brysbaert (2010); DE, Brysbaert, Buchmeier, Conrad, Jacobs, Bölte & Böhl (2011); NL, Keuleers, Brysbaert & New (2010)",
                    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                    "snapshot": "Language use through approximately 2021",
                    "underlying_sources": {
                        "Google Books Ngrams": "https://books.google.com/ngrams",
                        "Leeds Internet Corpus": "http://corpus.leeds.ac.uk/list.html",
                        "Wikipedia contributors": "https://www.wikipedia.org/",
                        "ParaCrawl": "https://paracrawl.eu/",
                        "OPUS OpenSubtitles 2018 / OpenSubtitles": "https://www.opensubtitles.org/",
                        "Freely available SUBTLEX lists, Marc Brysbaert et al.": "http://crr.ugent.be/programs-data/subtitle-frequencies",
                    }})
    table = FrequencyTable(
        built_at=datetime.now(timezone.utc).isoformat(), corpus_tokens=tokens, sources=sources,
        methodology=("VERB/AUX lemma occurrences per billion non-PUNCT/non-SYM tokens in UD German GSD; "
                     "compound:prt children restore separable prefixes. Automatic lemmas can be imperfect. "
                     "No corpus verb evidence: provisional wordfreq infinitive lookup capped at Zipf 2.5 "
                     "to prevent article/noun homographs from receiving high verb priority. "
                     "Small news/reviews/web corpus, not a representative frequency census."),
        words=words,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(table.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return table
