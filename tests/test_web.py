import http.client
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from deutsch.core import Exercise
from deutsch.frequencies import Frequency, FrequencyTable
from deutsch.history import load_history
from deutsch.vocabulary import VocabularyEntry
from deutsch.web import BrowserSession, LocalServer, RequestError, RogueOptions, WebConfig, practice_stats


def sample():
    return Exercise(word_id="gehen", sentence_id="gehen-01", infinitive="gehen",
                    italian="Vado a casa.", italian_target="Vado", german="Ich gehe nach Hause.", german_target="gehe")


def config(tmp_path, *, exercises=None, **options):
    exercises = exercises if exercises is not None else [sample()]
    entries = list({e.word_id: VocabularyEntry(word_id=e.word_id, infinitive=e.infinitive) for e in exercises}.values())
    frequencies = FrequencyTable(built_at="test", corpus_tokens=1000, sources=[], methodology="test",
                                 words={e.word_id: Frequency(infinitive=e.infinitive, zipf=5.81, method="lemma_pos", corpus_count=100) for e in exercises})
    defaults = dict(exercises=exercises, entries=entries, log_path=tmp_path / "guesses.jsonl", frequencies=frequencies)
    return WebConfig(**(defaults | options))


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def submit(session, raw):
    return session.submit(raw, session.presentation_id, str(uuid4()))


def flag(session, attempt):
    return session.submit("", session.presentation_id, str(uuid4()), attempt)


@contextmanager
def running_server(settings):
    server = LocalServer(settings, 0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.close_sessions()
        server.server_close()
        thread.join(timeout=5)


def request(server, method, path, payload=None, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload)
        headers.setdefault("Content-Type", "application/json")
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    content = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
    result = response.status, content, dict(response.getheaders())
    connection.close()
    return result


def test_initial_prompt_does_not_expose_german_answer_meaning_or_frequency(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    current = s.state()["current"]
    assert current["italian"] == sample().italian
    assert set(current) == {"presentation_id", "number", "italian", "italian_target", "attempts", "explanation"}
    assert s.state()["trail"] == []
    assert not s.config.log_path.exists()


def test_accepted_infinitive_completes_prompt_without_leaking_beforehand(tmp_path):
    exercise = sample().model_copy(update={"accepted_infinitives": ("laufen",)})
    s = BrowserSession(config(tmp_path, exercises=[exercise]), "random")
    assert "laufen" not in json.dumps(s.state())
    state = submit(s, " LAUFEN ")["state"]
    assert state["correct"] == 1
    assert state["trail"][0]["infinitive"] == "gehen"
    assert state["trail"][0]["accepted_infinitives"] == ["laufen"]
    assert "laufen" not in json.dumps(state["current"])
    assert load_history(s.config.log_path).presentations[0].score == 1


@pytest.mark.parametrize("mode", ["random", "adaptive"])
def test_near_miss_retry_and_reveal_match_cli_and_preserve_raw_guesses(tmp_path, mode):
    s = BrowserSession(config(tmp_path), mode)
    original = s.presentation_id
    a = submit(s, "  GEHN  ")["state"]
    assert a["current"]["presentation_id"] == original
    assert a["current"]["attempts"] == [{"guess": "  GEHN  ", "result": "almost_there"}]
    b = submit(s, " GEHEN ")["state"]
    assert b["correct"] == 1 and b["guesses"] == 2
    assert b["current"]["presentation_id"] != original
    revealed = b["trail"][0]
    assert revealed["german"] == sample().german
    assert revealed["popularity"] == 5.81 and revealed["infinitive"] == "gehen"
    assert [r["guess"] for r in records(s.config.log_path)] == ["  GEHN  ", " GEHEN "]
    assert [r["attempt"] for r in records(s.config.log_path)] == [1, 2]
    submit(s, "/q")
    assert [p.score for p in load_history(s.config.log_path).presentations] == [0.5, None]


def test_blank_reveals_but_whitespace_is_an_actual_guess(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    submit(s, "   ")
    state = submit(s, "")["state"]
    assert state["guesses"] == 1 and state["correct"] == 0
    assert state["trail"][0]["outcome"] == "gave_up"
    assert records(s.config.log_path)[0]["guess"] == "   "
    assert load_history(s.config.log_path).presentations[0].score == 0


def test_swiss_ss_is_accepted_while_display_stays_standard_german(tmp_path):
    ex = Exercise(word_id="heissen", sentence_id="heissen-01", infinitive="heißen", italian="Mi chiamo Marco.",
                  italian_target="Mi chiamo", german="Ich heiße Marco.", german_target="heiße")
    s = BrowserSession(config(tmp_path, exercises=[ex]), "random")
    state = submit(s, "heissen")["state"]
    assert state["trail"][0]["german"] == "Ich heiße Marco."
    assert state["correct"] == 1
    assert records(s.config.log_path)[0]["guess"] == "heissen"


def test_flags_synonym_attempt_of_previous_sentence_not_current_even_for_same_word(tmp_path):
    other = sample().model_copy(update={"sentence_id": "gehen-02", "italian": "Questo va bene.",
                                      "italian_target": "va", "german": "Das geht gut.", "german_target": "geht", "meaning": "funzionare"})
    s = BrowserSession(config(tmp_path, exercises=[sample(), other]), "random")
    previous = s.current
    first_id = s.presentation_id
    submit(s, "laufen")
    submit(s, "gehen")
    assert s.current.sentence_id != previous.sentence_id
    result = flag(s, 1)
    assert result["message"]["kind"] == "info"
    [record] = records(s.config.alternative_log)
    assert record["sentence_id"] == previous.sentence_id
    assert record["presentation_id"] == first_id
    assert record["synonym_guess"] == "laufen"
    assert result["state"]["guesses"] == 2
    assert result["state"]["current"]["attempts"] == []
    assert result["state"]["trail"][0]["flagged"] is True
    assert result["state"]["trail"][0]["attempts"][0]["flagged"] is True
    flag(s, 1)
    assert len(records(s.config.alternative_log)) == 1



def test_unflag_appends_a_withdrawal_and_clears_the_flag(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    first_id = s.presentation_id
    submit(s, "laufen")
    submit(s, "gehen")
    unflag = lambda attempt: s.submit("", s.presentation_id, str(uuid4()), attempt, True)
    assert "Nessuna" in unflag(1)["message"]["text"]
    assert not s.config.alternative_log.exists()
    flag(s, 1)
    result = unflag(1)
    requested, withdrawn = records(s.config.alternative_log)
    assert (requested["event"], withdrawn["event"]) == ("alternative_requested", "alternative_withdrawn")
    assert withdrawn["presentation_id"] == first_id and withdrawn["synonym_guess"] == "laufen"
    assert result["state"]["trail"][0]["flagged"] is False
    assert "flagged" not in result["state"]["trail"][0]["attempts"][0]
    assert result["state"]["guesses"] == 2
    flag(s, 1)
    assert len(records(s.config.alternative_log)) == 3
    with pytest.raises(RequestError):
        s.submit("", s.presentation_id, str(uuid4()), None, True)



def test_stats_count_answered_sentences_from_the_logs(tmp_path):
    settings = config(tmp_path)
    assert practice_stats(settings)["per_word"] == [{"word": "gehen", "attempts": 0, "wrong": 0, "almost": 0, "correct": 0, "popularity": 5.81, "provisional": False}]
    s = BrowserSession(settings, "random")
    submit(s, "gehen")   # first try
    submit(s, "laufen")
    submit(s, "gehen")   # second try
    submit(s, "")        # revealed; the next sentence is shown but unanswered
    stats = practice_stats(settings)
    assert {key: stats[key] for key in ["sentences", "first_try", "revealed", "words_seen", "words"]} == {"sentences": 3, "first_try": 1, "revealed": 1, "words_seen": 1, "words": 1}
    assert stats["words_guessed"] == 1
    assert stats["per_word"][0] == {"word": "gehen", "attempts": 3, "wrong": 2, "almost": 0, "correct": 1, "popularity": 5.81, "provisional": False}


def test_typed_alt_is_no_longer_a_command(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    submit(s, "gehen")
    submit(s, "/alt")
    assert not s.config.alternative_log.exists()
    assert records(s.config.log_path)[-1]["guess"] == "/alt"


def test_invalid_or_missing_flag_targets_are_neutral(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    assert "Nessun" in flag(s, 1)["message"]["text"]
    submit(s, "gehen")
    assert "non valido" in flag(s, 1)["message"]["text"]  # the correct attempt cannot be a synonym
    assert "non valido" in flag(s, 9)["message"]["text"]
    assert not s.config.alternative_log.exists()
    with pytest.raises(RequestError):
        s.submit("gehen", s.presentation_id, str(uuid4()), 1)


def test_quit_and_server_close_do_not_invent_failure_or_double_log(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    submit(s, "/quit")
    s.close()
    assert [e["event"] for e in records(s.config.events_path)] == ["presented", "abandoned"]
    assert load_history(s.config.log_path).presentations[0].score is None
    with pytest.raises(RequestError):
        submit(s, "gehen")


def test_adaptive_knowledge_updates_in_same_session(tmp_path):
    s = BrowserSession(config(tmp_path), "adaptive")
    before = s.deck.word_knowledge("gehen").mastery
    submit(s, "kommen")
    submit(s, "gehen")
    assert s.deck.word_knowledge("gehen").mastery < before
    assert s.history is s.deck.history
    assert s.history.presentations[0].score == 0


def test_flags_do_not_accept_synonyms_or_change_scoring(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    submit(s, "kommen")
    submit(s, "gehen")
    flag(s, 1)
    submit(s, "laufen")
    assert s.first_result == "incorrect"
    assert s.guesses == 3


def test_duplicate_network_request_is_idempotent_and_stale_answer_is_rejected(tmp_path):
    s = BrowserSession(config(tmp_path), "random")
    identifier = s.presentation_id
    first = s.submit("gehen", identifier, "request-1")
    assert s.submit("gehen", identifier, "request-1") == first
    assert len(records(s.config.log_path)) == 1
    with pytest.raises(RequestError) as error:
        s.submit("gehen", identifier, "request-2")
    assert error.value.status == 409
    with pytest.raises(RequestError):
        s.submit("wrong", identifier, "request-1")
    assert len(records(s.config.log_path)) == 1


@pytest.mark.parametrize("raw", [None, [], 3, "x" * 501])
def test_bad_answer_payload_is_not_logged(tmp_path, raw):
    s = BrowserSession(config(tmp_path), "random")
    with pytest.raises(RequestError):
        submit(s, raw)
    assert not s.config.log_path.exists()


def test_failed_guess_write_keeps_input_attempt_unscored_and_can_retry(tmp_path, monkeypatch):
    import deutsch.web as web
    s = BrowserSession(config(tmp_path), "random")
    original = web.append_guess
    def fail(*args, **kwargs):
        raise OSError("test write failure")
    monkeypatch.setattr(web, "append_guess", fail)
    with pytest.raises(OSError):
        submit(s, "gehen")
    assert s.guesses == 0 and s.attempts == [] and not s.ended
    monkeypatch.setattr(web, "append_guess", original)
    assert submit(s, "gehen")["state"]["correct"] == 1


def test_failed_terminal_event_stops_session_but_saved_guess_remains_recoverable(tmp_path, monkeypatch):
    import deutsch.web as web
    s = BrowserSession(config(tmp_path), "random")
    original = web.append_event
    def fail(*args, **kwargs):
        if args[4] == "completed":
            raise OSError("test event failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(web, "append_event", fail)
    with pytest.raises(OSError):
        submit(s, "gehen")
    assert s.ended and s.fatal_error
    assert load_history(s.config.log_path).presentations[0].score == 1


def test_failed_flag_write_is_retryable_without_extra_guesses(tmp_path):
    path = tmp_path / "blocked"
    path.mkdir()
    s = BrowserSession(config(tmp_path, alternative_log=path), "random")
    submit(s, "laufen")
    submit(s, "gehen")
    with pytest.raises(OSError):
        flag(s, 1)
    assert not s.flagged and s.guesses == 2
    path.rmdir()
    flag(s, 1)
    assert len(records(path)) == 1 and s.guesses == 2


def test_random_mode_does_not_require_frequencies_and_reveal_uses_unknown_label(tmp_path):
    settings = config(tmp_path, frequencies=None)
    assert settings.modes == ["random"]
    s = BrowserSession(settings, "random")
    assert submit(s, "")["state"]["trail"][0]["popularity"] is None
    with pytest.raises(RequestError):
        BrowserSession(settings, "adaptive")


def test_adaptive_excludes_flagged_entries_but_random_keeps_them(tmp_path):
    settings = config(tmp_path)
    settings.entries[0].review_note = "verify"
    assert "adaptive" not in settings.modes
    assert BrowserSession(settings, "random").current is not None


def test_rogue_ranks_unique_words_from_most_popular_at_or_below_cutoff(tmp_path):
    at_cutoff = sample().model_copy(update={"word_id": "machen", "sentence_id": "machen-01", "infinitive": "machen"})
    duplicate = sample().model_copy(update={"sentence_id": "gehen-02"})
    frequent = sample().model_copy(update={"word_id": "sein", "sentence_id": "sein-01", "infinitive": "sein"})
    missing = sample().model_copy(update={"word_id": "tun", "sentence_id": "tun-01", "infinitive": "tun"})
    settings = config(tmp_path, exercises=[sample(), duplicate, at_cutoff, frequent, missing])
    for word, score in {"gehen": 2.0, "machen": 3.0, "sein": 4.0}.items():
        settings.frequencies.words[word].zipf = score
    del settings.frequencies.words["tun"]
    s = BrowserSession(settings, "rogue", RogueOptions(max_popularity=3, lives=2, randomness=0))
    first = s.presentation_id
    assert s.current.word_id == "machen"
    assert "infinitive" not in s.state()["current"]
    retry = submit(s, "laufen")["state"]
    assert retry["current"]["presentation_id"] == first
    assert retry["rogue"] == {"initial_lives": 2, "lives_left": 2, "total": 2, "result": None}
    submit(s, "machen")
    assert s.current.word_id == "gehen"
    assert s.state()["rogue"]["lives_left"] == 2
    end = submit(s, "")["state"]
    assert end["ended"] and end["current"] is None and end["correct"] == 1
    assert [entry["popularity"] for entry in end["trail"]] == [3.0, 2.0]
    assert end["rogue"] == {"initial_lives": 2, "lives_left": 1, "total": 2, "result": "won"}
    assert [e["event"] for e in records(settings.events_path)] == ["presented", "completed", "presented", "gave_up"]


def test_rogue_last_skip_loses_even_on_final_word_and_can_flag_that_sentence(tmp_path):
    s = BrowserSession(config(tmp_path), "rogue", RogueOptions(max_popularity=9, lives=1))
    identifier = s.presentation_id
    submit(s, "  laufen  ")
    end = s.submit("", identifier, "skip")["state"]
    assert end == s.submit("", identifier, "skip")["state"]
    assert end["ended"] and end["current"] is None
    assert end["rogue"] == {"initial_lives": 1, "lives_left": 0, "total": 1, "result": "lost"}
    s.submit("", identifier, "flag", flag_attempt=1)
    [record] = records(s.config.alternative_log)
    assert record["sentence_id"] == sample().sentence_id and record["synonym_guess"] == "  laufen  "
    s.close()
    assert [e["event"] for e in records(s.config.events_path)] == ["presented", "gave_up"]


def test_rogue_randomness_favors_more_popular_words_by_their_zipf_gap(tmp_path):
    exercises = [sample().model_copy(update={"word_id": word, "sentence_id": f"{word}-01", "infinitive": word})
                 for word in ("gehen", "machen", "tun", "sein")]
    settings = config(tmp_path, exercises=exercises, seed=42)
    for word, score in {"gehen": 4.0, "machen": 3.5, "tun": 2.0, "sein": 5.0}.items():
        settings.frequencies.words[word].zipf = score
    options = RogueOptions(max_popularity=4, lives=3, randomness=1)
    seeded = settings.rogue_exercises(options)
    assert settings.rogue_exercises(options) == seeded

    close, far = 0, 0
    for seed in range(1000):
        settings.seed = seed
        order = [exercise.word_id for exercise in settings.rogue_exercises(options)]
        assert sorted(order) == ["gehen", "machen", "tun"]
        close += order.index("gehen") < order.index("machen")
        far += order.index("gehen") < order.index("tun")
    # Logistic odds for Zipf gaps of 0.5 and 2 at randomness 1.
    assert close / 1000 == pytest.approx(0.622, abs=0.05)
    assert far / 1000 == pytest.approx(0.881, abs=0.05)


def test_http_rogue_start_validates_options_and_replays_identical_request(tmp_path):
    with running_server(config(tmp_path)) as server:
        settings = {"mode": "rogue", "request_id": "rogue-1", "max_popularity": 9, "lives": 2}
        assert "rogue" in request(server, "GET", "/api/config")[1]["modes"]
        for invalid in [{"lives": 0}, {"lives": True}, {"max_popularity": -1}, {"max_popularity": 0},
                        {"randomness": -0.1}, {"randomness": 2.1}, {"randomness": "1"}]:
            assert request(server, "POST", "/api/start", settings | invalid)[0] == 400
        assert list(tmp_path.iterdir()) == []
        status, started, _ = request(server, "POST", "/api/start", settings)
        assert status == 200
        assert request(server, "POST", "/api/start", settings)[1] == started
        assert request(server, "POST", "/api/start", settings | {"lives": 1})[0] == 409
        assert request(server, "POST", "/api/start", settings | {"randomness": 0.1})[1] == started
        assert request(server, "POST", "/api/start", settings | {"randomness": 0})[0] == 409
        assert request(server, "POST", "/api/start", settings | {"randomness": 1})[0] == 409
        assert len(records(server.config.events_path)) == 1


@pytest.mark.parametrize("filename", ["guesses.jsonl", "guesses.events.jsonl"])
def test_log_collisions_rejected_before_writes(tmp_path, filename):
    with pytest.raises(ValueError, match="different paths"):
        config(tmp_path, alternative_log=tmp_path / filename)
    assert list(tmp_path.iterdir()) == []


def test_http_assets_do_not_start_practice_and_do_not_expose_files(tmp_path):
    with running_server(config(tmp_path)) as server:
        assert server.server_address[0] == "127.0.0.1"
        for path in ["/", "/app.css", "/app.js", "/favicon.svg"]:
            status, body, headers = request(server, "GET", path)
            assert status == 200 and body
            assert "unsafe-inline" not in headers["Content-Security-Policy"]
            assert headers["Cache-Control"] == "no-store"
        for path in ["/.env", "/data/guesses.jsonl", "/../pyproject.toml", "/%2e%2e/.env"]:
            assert request(server, "GET", path)[0] == 404
        assert list(tmp_path.iterdir()) == []


def test_http_session_reload_and_submission_deduplication(tmp_path):
    with running_server(config(tmp_path)) as server:
        status, started, _ = request(server, "POST", "/api/start", {"mode": "random", "request_id": "start-1"})
        assert status == 200
        duplicate = request(server, "POST", "/api/start", {"mode": "random", "request_id": "start-1"})[1]
        assert duplicate["token"] == started["token"]
        assert len(records(server.config.events_path)) == 1
        headers = {"X-Deutsch-Session": started["token"]}
        identifier = started["state"]["current"]["presentation_id"]
        state = request(server, "GET", "/api/state", headers=headers)[1]["state"]
        assert state["current"]["presentation_id"] == identifier
        payload = {"guess": " GEHEN ", "presentation_id": identifier, "request_id": "answer-1"}
        assert request(server, "POST", "/api/submit", payload, headers)[0] == 200
        assert request(server, "POST", "/api/submit", payload, headers)[0] == 200
        assert len(records(server.config.log_path)) == 1
        assert records(server.config.log_path)[0]["guess"] == " GEHEN "
        assert request(server, "GET", "/api/state")[0] == 404
        assert request(server, "POST", "/api/submit", payload)[0] == 404


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"}, {"Host": "evil.example"}])
def test_http_rejects_cross_origin_and_dns_rebinding_before_writes(tmp_path, headers):
    with running_server(config(tmp_path)) as server:
        assert request(server, "POST", "/api/start", {"request_id": "start"}, headers)[0] == 403
        assert list(tmp_path.iterdir()) == []


def test_http_rejects_bad_json_types_and_non_json_posts(tmp_path):
    with running_server(config(tmp_path)) as server:
        assert request(server, "POST", "/api/start", body="mode=random", headers={"Content-Type": "text/plain"})[0] == 415
        assert request(server, "POST", "/api/start", body="{bad", headers={"Content-Type": "application/json"})[0] == 400
        assert request(server, "POST", "/api/start", payload=[])[0] == 400
        assert request(server, "POST", "/api/start", payload={"request_id": "start", "mode": []})[0] == 400
        assert request(server, "POST", "/api/start", body="x" * 16_385, headers={"Content-Type": "application/json"})[0] == 413
        assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("period", "expected"), [("day", 1), ("month", 2), ("year", 3), ("all", 4)])
def test_stats_time_windows_are_inclusive_read_only_and_do_not_count_retries(tmp_path, period, expected):
    settings = config(tmp_path)
    now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    rows = []
    for i, age in enumerate([1, 30, 365, 1000]):
        for attempt, result in [(1, "almost_there"), (2, "correct")]:
            rows.append(dict(schema_version=2, presentation_id=str(i), session_id="old", word_id="gehen", sentence_id="gehen-01",
                             expected_infinitive="gehen", timestamp=(now - timedelta(days=age)).isoformat(),
                             attempt=attempt, result=result))
    # Future timestamps must not be counted, even in all-time reports.
    rows.append(dict(rows[0], presentation_id="future", timestamp=(now + timedelta(days=1001)).isoformat()))
    settings.log_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    before = settings.log_path.read_bytes()
    stats = practice_stats(settings, period, now=now)
    assert stats["sentences"] == expected
    assert stats["words_guessed"] == 1
    assert stats["per_word"][0]["almost"] == expected
    assert stats["per_word"][0]["correct"] == 0
    assert settings.log_path.read_bytes() == before
    assert not settings.events_path.exists()
    # One second past the oldest included observation drops it from this window.
    if period != "all":
        assert practice_stats(settings, period, now=now + timedelta(seconds=1))["sentences"] == expected - 1


def test_stats_include_unseen_catalog_words_missing_popularity_and_history_warnings(tmp_path):
    settings = config(tmp_path)
    settings.entries.append(VocabularyEntry(word_id="heissen", infinitive="heißen"))
    settings.log_path.write_text("broken json\n")
    stats = practice_stats(settings)
    assert stats["words"] == 2 and stats["words_seen"] == 0
    assert stats["per_word"][1] == dict(word="heißen", attempts=0, wrong=0, almost=0, correct=0, popularity=None, provisional=False)
    assert stats["warnings"]
    assert "sentence_id" not in json.dumps(stats["per_word"])
    assert "german" not in json.dumps(stats["per_word"])


def test_stats_reveal_overrides_near_miss_and_ignores_unattempted_prompts(tmp_path):
    settings = config(tmp_path)
    session = BrowserSession(settings, "random")
    submit(session, "gehn")
    submit(session, "")
    session.close()
    stats = practice_stats(settings)
    assert stats["sentences"] == 1 and stats["revealed"] == 1
    assert stats["per_word"][0]["wrong"] == 1
    assert stats["per_word"][0]["almost"] == 0
    assert stats["words_guessed"] == 0


def test_stats_http_periods_and_invalid_queries_do_not_write_history(tmp_path):
    with running_server(config(tmp_path)) as server:
        for period in ["all", "year", "month", "day"]:
            status, body, _ = request(server, "GET", "/api/stats?period=" + period)
            assert status == 200 and body["period"] == period
            assert len(body["per_word"]) == 1
        for query in ["period=week", "period=", "period=all&period=day", "other=day"]:
            assert request(server, "GET", "/api/stats?" + query)[0] == 400
        assert list(tmp_path.iterdir()) == []


def test_stats_distinct_guessed_includes_retries_but_not_near_misses(tmp_path):
    settings = config(tmp_path)
    other = sample().model_copy(update=dict(word_id="laufen", sentence_id="laufen-01", infinitive="laufen"))
    settings.entries.append(VocabularyEntry(word_id="laufen", infinitive="laufen"))
    session = BrowserSession(settings, "random")
    submit(session, "gehn")
    submit(session, "gehen")
    submit(session, "gehen")
    # A guessed word counts once even across separate presentations and senses.
    assert practice_stats(settings)["words_guessed"] == 1
    assert practice_stats(settings)["per_word"][0]["almost"] == 1
    assert practice_stats(settings)["per_word"][0]["correct"] == 1
    assert practice_stats(settings)["words"] == 2
    from deutsch.core import append_guess
    append_guess(settings.log_path, other, "laufn", "old", 1)
    assert practice_stats(settings)["words_guessed"] == 1
    append_guess(settings.log_path, other, "laufen", "old", 2)
    assert practice_stats(settings)["words_guessed"] == 2


def test_stats_missing_first_attempt_can_count_guessed_word_without_inventing_recall(tmp_path):
    settings = config(tmp_path)
    from deutsch.core import append_guess
    append_guess(settings.log_path, sample(), "gehen", "old", 2)
    stats = practice_stats(settings)
    assert stats["words_guessed"] == 1
    assert stats["first_try"] == 0 and stats["sentences"] == 0
    assert stats["per_word"][0]["correct"] == 0


def test_stats_attempt_totals_include_retries_and_sort_most_attempted_first(tmp_path):
    settings = config(tmp_path)
    settings.entries.append(VocabularyEntry(word_id="arbeiten", infinitive="arbeiten"))
    from deutsch.core import append_guess
    other = sample().model_copy(update=dict(word_id="arbeiten", sentence_id="arbeiten-01", infinitive="arbeiten"))
    append_guess(settings.log_path, other, "arbeiten", "session", 1)
    for attempt, guess in enumerate(["laufen", "gehn", "gehen"], 1):
        append_guess(settings.log_path, sample(), guess, "session", attempt)
    stats = practice_stats(settings)
    assert stats["attempts"] == 4 and stats["correct_attempts"] == 2
    assert stats["words_guessed"] == 2 and stats["words"] == 2
    assert [row["word"] for row in stats["per_word"]] == ["gehen", "arbeiten"]
    assert stats["per_word"][0]["attempts"] == 3
    # The stacked chart still measures first recall, separately from retry totals.
    assert stats["per_word"][0]["wrong"] == 1
    assert stats["per_word"][0]["correct"] == 0
