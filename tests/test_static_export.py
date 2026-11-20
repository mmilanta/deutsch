import json

from deutsch.core import Exercise
from deutsch.static_export import export_game


def test_export_publishes_only_relative_game_assets(tmp_path):
    exercise = Exercise(word_id="gehen", sentence_id="gehen-01", infinitive="gehen",
                        italian="Io vado.", italian_target="vado", german="Ich gehe.", german_target="gehe",
                        accepted_infinitives=("laufen",))
    (tmp_path / "guesses.jsonl").write_text("private history")
    output = tmp_path / "site"
    export_game(output, [exercise], {exercise.sentence_id: -1.25})
    assert {str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()} == {
        ".nojekyll", "index.html", "404.html", "app.css", "app.js", "favicon.svg", "static-game.js", "deck.js", "answers/0.js",
    }
    html = (output / "index.html").read_text()
    assert 'src="/' not in html and 'href="/' not in html
    assert 'id="stats-tab"' not in html and 'id="stats"' not in html
    assert html.index('src="deck.js"') < html.index('src="static-game.js"') < html.index('src="app.js"')
    fallback = (output / "404.html").read_text()
    assert fallback.index('createElement("base")') < fallback.index('href="favicon.svg"')
    assert fallback.replace(fallback[fallback.index("  <script>"):fallback.index("</script>\n") + 10], "") == html
    deck = (output / "deck.js").read_text()
    [card] = json.loads(deck.split(" = ", 1)[1].removesuffix(";\n"))["cards"]
    assert card["italian"] == exercise.italian and card["difficulty"] == -1.25
    assert not any(text in deck for text in (exercise.german, exercise.infinitive, "laufen"))
    assert len(card["target"]) == len(card["alternatives"][0]) == 64
    assert exercise.german in (output / "answers/0.js").read_text()
