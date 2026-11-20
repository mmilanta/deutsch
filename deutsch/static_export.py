"""Build a self-contained browser game from public exercise assets only."""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

from deutsch.core import Exercise, normalize


def _digest(salt: str, word: str) -> str:
    return hashlib.sha256(f"{salt}:{normalize(word)}".encode()).hexdigest()


def export_game(output: Path, exercises: list[Exercise], difficulty: dict[str, float]) -> None:
    assets = files("deutsch").joinpath("static")
    index = assets.joinpath("index.html").read_text(encoding="utf-8")
    # The static site has no statistics, API, or browser storage. All URLs
    # are relative so the export also works under a GitHub project subpath.
    index = index.replace('href="/', 'href="').replace('src="/', 'src="')
    index = index.replace('    <button type="button" id="stats-tab" aria-pressed="false">Stats</button>\n', '')
    index = index.replace('    <section id="stats" aria-label="Statistiche" hidden></section>\n', '')
    index = index.replace('  <script src="app.js" defer></script>',
                          '  <script src="deck.js" defer></script>\n'
                          '  <script src="static-game.js" defer></script>\n'
                          '  <script src="app.js" defer></script>')
    output.mkdir(parents=True)
    answers = output / "answers"
    answers.mkdir()
    for name in ("app.css", "app.js", "static-game.js", "favicon.svg"):
        (output / name).write_bytes(assets.joinpath(name).read_bytes())
    alphabet = sorted(set("".join(normalize(e.infinitive) for e in exercises)))
    cards = []
    for i, exercise in enumerate(exercises):
        key = str(i)
        cards.append({"key": key, "italian": exercise.italian, "italian_target": exercise.italian_target,
                      "difficulty": difficulty.get(exercise.sentence_id),
                      "length": len(normalize(exercise.infinitive)),
                      "target": _digest(key, exercise.infinitive),
                      "alternatives": [_digest(key, alt) for alt in exercise.accepted_infinitives or ()]})
        reveal = exercise.model_dump(include={"infinitive", "german", "german_target", "meaning", "accepted_infinitives"},
                                     exclude_none=True)
        (answers / f"{key}.js").write_text(f"DeutschStatic.reveal({json.dumps(key)}, {json.dumps(reveal)});\n", encoding="utf-8")
    deck = json.dumps({"alphabet": alphabet, "cards": cards}, ensure_ascii=True, separators=(",", ":"))
    (output / "deck.js").write_text(f"globalThis.DeutschDeck = {deck};\n", encoding="utf-8")
    (output / "index.html").write_text(index, encoding="utf-8")
    # GitHub Pages serves 404.html for unknown paths such as {site}/game/3-0.05-42.
    # Re-root relative asset URLs at the site directory before any are resolved.
    rebase = ('<script>(() => { const m = location.pathname.match(/^(.*\\/)game\\/[^/]*\\/?$/); '
              'if (m) { const base = document.createElement("base"); base.href = m[1]; '
              'document.head.append(base); } })();</script>\n')
    (output / "404.html").write_text(index.replace("<head>\n", "<head>\n  " + rebase, 1), encoding="utf-8")
    (output / ".nojekyll").touch()
