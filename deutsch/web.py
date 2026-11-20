"""A loopback-only browser interface. No framework, remote assets, or model calls."""
from __future__ import annotations

import json
import re
import secrets
import threading
import webbrowser
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from deutsch.core import Exercise, append_guess
from deutsch.difficulty import MAX_SEED, GameOptions, ordered_exercises
from deutsch.frequencies import FrequencyTable
from deutsch.history import append_event, events_path_for, load_history
from deutsch.review import alternative_log_for, append_alternative_flag
from deutsch.vocabulary import VocabularyEntry, audit_vocabulary

# /game/{lives}-{randomness}-{seed}: the app shell; app.js starts or resumes that match.
GAME_PATH = re.compile(r"/game/\d{1,16}-\d{1,3}(?:\.\d{1,6})?-\d{1,10}")


class RequestError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class WebConfig:
    exercises: list[Exercise]
    entries: list[VocabularyEntry]
    log_path: Path
    frequencies: FrequencyTable | None = None
    events_path: Path | None = None
    alternative_log: Path | None = None
    difficulty: dict[str, float] = field(default_factory=dict)
    threshold: int = 1
    seed: int | None = None

    def __post_init__(self):
        self.events_path = self.events_path if self.events_path is not None else events_path_for(self.log_path)
        self.alternative_log = self.alternative_log if self.alternative_log is not None else alternative_log_for(self.log_path)
        paths = [self.log_path, self.events_path, self.alternative_log]
        if len({path.resolve() for path in paths}) != len(paths):
            raise ValueError("Guess, presentation-event, and alternative-review logs must use different paths")
        errors = audit_vocabulary(self.entries, self.exercises).errors
        if errors:
            raise ValueError("; ".join(errors))
        if not self.exercises:
            raise ValueError("The deck must contain at least one exercise")
        if self.threshold < 0:
            raise ValueError("Invalid threshold")


def practice_stats(config: WebConfig, period: str = "all", *, now: datetime | None = None) -> dict:
    """One observation per presentation; never return sentence answers or IDs."""
    days = {"all": None, "year": 365, "month": 30, "day": 1}
    if period not in days:
        raise RequestError("Periodo non valido.")
    now = now if now is not None else datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days[period]) if days[period] is not None else None
    history = load_history(config.log_path, config.events_path)
    answered = []
    guessed = set()
    attempts = correct_attempts = 0
    rows = []
    for entry in sorted(config.entries, key=lambda entry: (entry.infinitive.casefold(), entry.word_id)):
        observations = [item for item in history.for_word(entry.word_id, entry.infinitive)
                        if item.timestamp <= now and (cutoff is None or item.timestamp >= cutoff)]
        if any(item.completed and not item.gave_up for item in observations):
            guessed.add(entry.word_id)
        word_attempts = sum(item.attempts for item in observations)
        attempts += word_attempts
        correct_attempts += sum(item.correct_attempts for item in observations)
        observations = [item for item in observations if item.first_result is not None or item.gave_up]
        answered.extend(observations)
        frequency = config.frequencies.for_word(entry.word_id, entry.infinitive) if config.frequencies else None
        correct = sum(item.first_result == "correct" and not item.gave_up for item in observations)
        almost = sum(item.first_result == "almost_there" and not item.gave_up for item in observations)
        rows.append({
            "word": entry.infinitive, "correct": correct, "almost": almost,
            "attempts": word_attempts,
            "wrong": len(observations) - correct - almost,
            "popularity": frequency.zipf if frequency and frequency.method != "missing" else None,
            "provisional": frequency is not None and frequency.method == "surface_fallback",
        })
    rows.sort(key=lambda row: (-row["attempts"], row["word"].casefold()))
    return {
        "sentences": len(answered),
        "first_try": sum(item.first_result == "correct" and not item.gave_up for item in answered),
        "revealed": sum(item.gave_up for item in answered),
        "words_seen": len({item.word_id for item in answered}),
        "words_guessed": len(guessed),
        "attempts": attempts, "correct_attempts": correct_attempts,
        "words": len(rows), "per_word": rows, "period": period,
        "warnings": history.warnings,
    }


class BrowserSession:
    """Browser state; uses the CLI's evaluator, decks, and append-only log writers."""

    def __init__(self, config: WebConfig, options: GameOptions = GameOptions()):
        self.config = config
        # Pin a concrete seed so the state can name a shareable /game/ URL.
        seed = options.seed if options.seed is not None else config.seed
        seed = seed & MAX_SEED if seed is not None else secrets.randbelow(MAX_SEED + 1)
        self.options = options = replace(options, seed=seed)
        exercises = ordered_exercises(config.exercises, config.difficulty, options)
        self.deck = iter(exercises)
        self.total = len(exercises)
        self.lives_left = options.lives
        self.result: str | None = None
        self.session_id = str(uuid4())
        self.current: Exercise | None = None
        self.presentation_id: str | None = None
        self.attempts: list[dict] = []
        self.first_result: str | None = None
        self.previous: tuple[Exercise, str] | None = None
        self.flagged: set[tuple[str, int]] = set()
        self.trail: list[dict] = []
        self.correct = self.guesses = 0
        self.ended = False
        self.fatal_error: str | None = None
        self.responses: OrderedDict[str, tuple[tuple, dict]] = OrderedDict()
        self._next()

    def _next(self):
        exercise = next(self.deck, None)
        if exercise is None:
            self.ended = True
            self.result = "won"
            return
        identifier = str(uuid4())
        append_event(self.config.events_path, exercise, self.session_id, identifier, "presented")
        self.current, self.presentation_id = exercise, identifier
        self.attempts, self.first_result = [], None

    def _prompt(self) -> dict | None:
        if self.current is None:
            return None
        # No German answer, meaning label, difficulty, or canonical word ID is
        # sent to the browser until this presentation has been revealed.
        return {
            "presentation_id": self.presentation_id,
            "number": len(self.trail) + 1,
            "italian": self.current.italian,
            "italian_target": self.current.italian_target,
            "attempts": list(self.attempts),
        }

    def state(self) -> dict:
        return {
            "current": self._prompt(), "trail": list(self.trail),
            "correct": self.correct, "guesses": self.guesses, "ended": self.ended,
            "fatal_error": self.fatal_error,
            "game": {"initial_lives": self.options.lives, "lives_left": self.lives_left,
                     "total": self.total, "result": self.result,
                     "randomness": self.options.randomness, "seed": self.options.seed},
        }

    def _finish(self, event: str):
        try:
            append_event(self.config.events_path, self.current, self.session_id, self.presentation_id,
                         event, attempts=sum(a["result"] != "valid_alternative" for a in self.attempts),
                         first_result=self.first_result)
        except OSError:
            self.ended = True
            self.fatal_error = "Evento non salvato. Sessione interrotta: controlla i file di cronologia prima di ricominciare."
            raise
        if event == "abandoned":
            self.ended = True
            return
        completed = self._prompt()
        completed.update(
            german=self.current.german, german_target=self.current.german_target,
            infinitive=self.current.infinitive, meaning=self.current.meaning,
            difficulty=self.config.difficulty.get(self.current.sentence_id),
            outcome=event, flagged=False,
        )
        if self.current.accepted_infinitives:
            completed["accepted_infinitives"] = list(self.current.accepted_infinitives)
        self.previous = (self.current, self.presentation_id)
        self.trail.append(completed)
        self.current, self.presentation_id = None, None
        if event == "gave_up":
            self.lives_left -= 1
            if self.lives_left == 0:
                self.ended = True
                self.result = "lost"
                return
        try:
            self._next()
        except OSError:
            self.ended = True
            self.fatal_error = "Impossibile salvare il prossimo esercizio. Sessione interrotta; le risposte precedenti sono salvate."
            raise

    def _flag(self, attempt: int) -> dict:
        """Flag the previous completed/revealed sentence, naming the attempt
        (1-based) the user considers a valid synonym."""
        if self.previous is None:
            return {"kind": "info", "text": "Nessun esercizio precedente da segnalare."}
        exercise, identifier = self.previous
        entry = self.trail[-1]
        if not 1 <= attempt <= len(entry["attempts"]) or entry["attempts"][attempt - 1]["result"] not in {"incorrect", "almost_there"}:
            return {"kind": "info", "text": "Tentativo non valido."}
        if (identifier, attempt) in self.flagged:
            return {"kind": "info", "text": "Già segnalato."}
        append_alternative_flag(self.config.alternative_log, exercise, self.session_id, identifier,
                                synonym_guess=entry["attempts"][attempt - 1]["guess"])
        self.flagged.add((identifier, attempt))
        entry["flagged"] = True
        entry["attempts"] = [dict(a, flagged=True) if i == attempt - 1 else a for i, a in enumerate(entry["attempts"])]
        return {"kind": "info", "text": "Sinonimo segnalato per revisione."}

    def _unflag(self, attempt: int) -> dict:
        """Withdraw a flag on the previous sentence by appending a withdrawal."""
        if self.previous is None or (self.previous[1], attempt) not in self.flagged:
            return {"kind": "info", "text": "Nessuna segnalazione da rimuovere."}
        exercise, identifier = self.previous
        entry = self.trail[-1]
        append_alternative_flag(self.config.alternative_log, exercise, self.session_id, identifier,
                                synonym_guess=entry["attempts"][attempt - 1]["guess"], withdrawn=True)
        self.flagged.discard((identifier, attempt))
        entry["attempts"] = [{k: v for k, v in a.items() if k != "flagged"} if i == attempt - 1 else a
                             for i, a in enumerate(entry["attempts"])]
        entry["flagged"] = any(a.get("flagged") for a in entry["attempts"])
        return {"kind": "info", "text": "Segnalazione rimossa."}

    def submit(self, raw: str, presentation_id: str, request_id: str, flag_attempt: int | None = None,
               unflag: bool = False) -> dict:
        if not isinstance(raw, str) or len(raw) > 500:
            raise RequestError("La risposta deve essere un testo di massimo 500 caratteri.")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise RequestError("Identificatore della richiesta non valido.")
        if not isinstance(presentation_id, str) or not presentation_id:
            raise RequestError("Identificatore dell’esercizio non valido.")
        if flag_attempt is not None and (type(flag_attempt) is not int or raw != ""):
            raise RequestError("Segnalazione non valida.")
        if type(unflag) is not bool or (unflag and flag_attempt is None):
            raise RequestError("Segnalazione non valida.")
        signature = (raw, presentation_id, flag_attempt, unflag)
        if request_id in self.responses:
            previous_signature, response = self.responses[request_id]
            if previous_signature != signature:
                raise RequestError("Richiesta già usata con un contenuto diverso.", 409)
            return response
        final_flag = flag_attempt is not None and self.result is not None
        expected_id = self.previous[1] if final_flag else self.presentation_id
        if (self.ended and not final_flag) or presentation_id != expected_id:
            raise RequestError("Esercizio non più attivo. Aggiorna lo stato prima di rispondere.", 409)
        command = raw.strip().lower()
        message = None
        if flag_attempt is not None:
            message = self._unflag(flag_attempt) if unflag else self._flag(flag_attempt)
        elif command in {"/q", "/quit"}:
            self._finish("abandoned")
        elif raw == "":
            self._finish("gave_up")
        else:
            result = append_guess(self.config.log_path, self.current, raw, self.session_id,
                                  len(self.attempts) + 1, self.config.threshold, presentation_id=self.presentation_id)
            self.attempts.append({"guess": raw, "result": result})
            if result != "valid_alternative":
                self.guesses += 1
                if self.first_result is None:
                    self.first_result = result
            if result == "correct":
                self.correct += 1
                self._finish("completed")
        response = {"state": self.state(), "message": message}
        self.responses[request_id] = (signature, response)
        while len(self.responses) > 256:
            self.responses.popitem(last=False)
        return response

    def close(self):
        if not self.ended:
            self._finish("abandoned")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: WebConfig, port: int = 8765):
        self.config = config
        self.sessions: dict[str, BrowserSession] = {}
        self.starts: dict[str, tuple[GameOptions, str]] = {}
        self.lock = threading.RLock()
        super().__init__(("127.0.0.1", port), Handler)

    def close_sessions(self):
        with self.lock:
            for session in self.sessions.values():
                try:
                    session.close()
                except OSError:
                    print("Warning: unable to save an abandoned browser presentation.")


class Handler(BaseHTTPRequestHandler):
    server: LocalServer
    assets = {"/": ("index.html", "text/html; charset=utf-8"),
              "/app.css": ("app.css", "text/css; charset=utf-8"),
              "/app.js": ("app.js", "text/javascript; charset=utf-8"),
              "/favicon.svg": ("favicon.svg", "image/svg+xml")}

    def log_message(self, *_):
        pass

    def _trusted(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            hosts.update({"127.0.0.1", "localhost"})
        if self.headers.get("Host") not in hosts:
            raise RequestError("Host non consentito.", 403)
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{host}" for host in hosts}:
            raise RequestError("Origine non consentita.", 403)

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict):
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _session(self) -> BrowserSession:
        token = self.headers.get("X-Deutsch-Session", "")
        if token not in self.server.sessions:
            raise RequestError("Sessione non trovata. Inizia una nuova sessione.", 404)
        return self.server.sessions[token]

    def do_GET(self):
        try:
            self._trusted()
            if self.path in self.assets or GAME_PATH.fullmatch(self.path):
                filename, content_type = self.assets.get(self.path, self.assets["/"])
                self._send(200, files("deutsch").joinpath("static", filename).read_bytes(), content_type)
            elif self.path == "/api/config":
                self._json(200, {"sentence_count": len(self.server.config.exercises)})
            elif urlsplit(self.path).path == "/api/stats":
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) - {"period"} or len(query.get("period", ["all"])) != 1:
                    raise RequestError("Periodo non valido.")
                with self.server.lock:
                    self._json(200, practice_stats(self.server.config, query.get("period", ["all"])[0]))
            elif self.path == "/api/state":
                with self.server.lock:
                    self._json(200, {"state": self._session().state()})
            else:
                raise RequestError("Pagina non trovata.", 404)
        except RequestError as error:
            self._json(error.status, {"error": str(error)})

    def do_POST(self):
        session = None
        try:
            self._trusted()
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                raise RequestError("È richiesto application/json.", 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise RequestError("Lunghezza della richiesta non valida.") from None
            if not 0 < length <= 16_384:
                raise RequestError("Richiesta vuota o troppo grande.", 413)
            try:
                payload = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                raise RequestError("JSON non valido.") from None
            if not isinstance(payload, dict):
                raise RequestError("La richiesta deve essere un oggetto JSON.")
            with self.server.lock:
                if self.path == "/api/start":
                    identifier = payload.get("request_id")
                    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128:
                        raise RequestError("Identificatore della richiesta non valido.")
                    if set(payload) - {"request_id", "lives", "randomness", "seed"}:
                        raise RequestError("Impostazioni di gioco non valide.")
                    try:
                        options = GameOptions(lives=payload.get("lives", 3), randomness=payload.get("randomness", 0),
                                              seed=payload.get("seed"))
                    except ValueError as error:
                        raise RequestError(str(error)) from error
                    if identifier in self.server.starts:
                        previous_options, token = self.server.starts[identifier]
                        if previous_options != options:
                            raise RequestError("Richiesta già usata con un contenuto diverso.", 409)
                    else:
                        if len(self.server.sessions) >= 64:
                            raise RequestError("Troppe sessioni aperte. Riavvia il server locale.", 429)
                        session = BrowserSession(self.server.config, options)
                        token = secrets.token_urlsafe(32)
                        self.server.sessions[token] = session
                        self.server.starts[identifier] = (options, token)
                    self._json(200, {"token": token, "state": self.server.sessions[token].state()})
                elif self.path == "/api/submit":
                    session = self._session()
                    response = session.submit(payload.get("guess"), payload.get("presentation_id"), payload.get("request_id"),
                                              payload.get("flag_attempt"), payload.get("unflag", False))
                    self._json(200, response)
                else:
                    raise RequestError("Pagina non trovata.", 404)
        except RequestError as error:
            self._json(error.status, {"error": str(error)})
        except OSError as error:
            self._json(503, {"error": f"Salvataggio non riuscito: {error}. Nessuna risposta viene ignorata in silenzio.",
                             "state": session.state() if session is not None else None})


def serve(config: WebConfig, port: int = 8765, open_browser: bool = False):
    with LocalServer(config, port) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"Deutsch · {url}", flush=True)
        print("Solo localhost · nessuna API esterna · Ctrl+C per fermare", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer locale fermato.")
        finally:
            server.close_sessions()
