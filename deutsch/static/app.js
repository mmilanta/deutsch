"use strict";

const $ = (id) => document.getElementById(id);
const staticGame = globalThis.DeutschStatic;
const storage = staticGame ? null : sessionStorage;
const labels = {
  correct: "Corretto.",
  almost_there: "Quasi.",
  incorrect: "Non ancora.",
  valid_alternative: "Traduzione valida, ma cerchiamo un altro verbo.",
};
let state = null;
let token = storage?.getItem("deutsch.session");
let busy = false;
let pending = null;
let view = "setup";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function highlighted(sentence, target) {
  const fragment = document.createDocumentFragment();
  const at = sentence.indexOf(target);
  if (at < 0) return document.createTextNode(sentence);
  fragment.append(document.createTextNode(sentence.slice(0, at)));
  fragment.append(element("strong", "", target));
  fragment.append(document.createTextNode(sentence.slice(at + target.length)));
  return fragment;
}

// Attempts on the exercise in progress: the guess and a short verdict.
function attemptsView(attempts) {
  const fragment = document.createDocumentFragment();
  for (const attempt of attempts) {
    const row = element("p", "attempt");
    row.append(element("span", "typed", attempt.guess));
    row.append(element("span", `feedback-${attempt.result}`, labels[attempt.result]));
    fragment.append(row);
  }
  return fragment;
}

// A completed sentence: one row per non-target guess, then the solution, green
// if it was guessed and red if it was revealed. Pressing a wrong guess of
// the latest sentence flags it as a possible synonym for that sentence only;
// pressing the flag withdraws it.
function historyView(previous, flaggable) {
  const fragment = document.createDocumentFragment();
  for (const [index, attempt] of previous.attempts.entries()) {
    if (attempt.result === "correct") continue;
    const isAlternative = attempt.result === "valid_alternative";
    const canFlag = flaggable && !attempt.flagged && !isAlternative;
    const row = element(canFlag ? "button" : "p", "attempt");
    if (canFlag) {
      row.type = "button";
      row.dataset.attempt = String(index + 1);
      row.title = "Segnala come sinonimo";
    }
    row.append(element("span", "typed", attempt.guess));
    if (isAlternative) row.append(element("span", "feedback-valid_alternative", "Traduzione valida"));
    if (attempt.flagged) {
      // On the latest sentence the flag is a button that withdraws it.
      const mark = element(flaggable ? "button" : "span", "flag", "⚑");
      if (flaggable) {
        mark.type = "button";
        mark.dataset.attempt = String(index + 1);
        mark.dataset.unflag = "";
        mark.title = "Rimuovi segnalazione";
        mark.setAttribute("aria-label", "Rimuovi segnalazione");
      }
      row.append(mark);
    }
    fragment.append(row);
  }
  const guessed = previous.outcome !== "gave_up";
  const solution = element("p", `attempt solution ${guessed ? "solution-guessed" : "solution-revealed"}`);
  solution.append(element("span", "typed", previous.infinitive));
  if (typeof previous.difficulty === "number") {
    const difficulty = element("span", "popularity", previous.difficulty.toFixed(2));
    difficulty.title = "Difficoltà stimata della frase";
    solution.append(difficulty);
  }
  fragment.append(solution);
  if (previous.accepted_infinitives?.length) {
    fragment.append(element("p", "attempt", `altre traduzioni valide: ${previous.accepted_infinitives.join(", ")}`));
  }
  return fragment;
}

function notify(id, text) {
  $(id).textContent = text || "";
  $(id).hidden = !text;
}

function controls() {
  const active = state && !state.ended;
  for (const id of ["answer", "submit-answer", "game-skip"]) {
    $(id).disabled = busy || !active;
  }
  for (const id of ["restart", "resume", "game-start", "game-lives", "game-randomness", "play-tab", "stats-tab"]) {
    if ($(id)) $(id).disabled = busy;
  }
}

// The Stats tab replaces the practice view; the session keeps running.
function show() {
  const stats = view === "stats";
  const practice = view === "practice";
  $("play-tab").setAttribute("aria-pressed", String(!stats));
  $("stats-tab")?.setAttribute("aria-pressed", String(stats));
  if ($("stats")) $("stats").hidden = !stats;
  $("game-setup").hidden = view !== "setup";
  $("resume").hidden = !state;
  $("resume").textContent = state?.ended ? "Ultima partita" : "Riprendi partita";
  $("trail").hidden = !practice;
  $("game-hud").hidden = !practice || !state || (state.ended && !state.game.result);
  $("exercise").hidden = !practice || !state?.current || state.ended;
  $("session-end").hidden = !practice || !state?.ended;
}

function figure(value, label) {
  const node = element("p", "figure");
  node.append(element("b", "", String(value)), element("span", "", label));
  return node;
}


let statsPeriod = "all";
let statsRelative = false;
let statsData = null;
let statsRequest = 0;
let statsSort = "attempts";

function sortedStatsRows(rows, sort) {
  return [...rows].sort((a, b) => {
    const alphabetical = a.word.localeCompare(b.word, "de");
    if (sort === "word") return alphabetical;
    if (sort === "popularity") return (b.popularity ?? -1) - (a.popularity ?? -1) || alphabetical;
    return b.attempts - a.attempts || alphabetical;
  });
}

function statsSortButton(className, sort, label, text) {
  const button = element("button", className, text);
  button.type = "button";
  button.dataset.sort = sort;
  button.setAttribute("aria-label", label);
  button.title = label;
  return button;
}

function statsButtons(label, choices, selected, onSelect) {
  const group = element("div", "stats-options");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", label);
  for (const [value, text] of choices) {
    const button = element("button", "", text);
    button.type = "button";
    button.dataset.value = value;
    button.setAttribute("aria-pressed", String(value === selected));
    button.addEventListener("click", () => onSelect(value));
    group.append(button);
  }
  return group;
}

function renderStats(loading = false) {
  const root = $("stats");
  root.setAttribute("aria-busy", String(loading));
  const header = element("div", "stats-heading");
  const filters = element("div", "stats-filters");
  filters.append(
    statsButtons("Periodo", [["all", "Sempre"], ["year", "Ultimo anno"], ["month", "Ultimo mese"], ["day", "Ultimo giorno"]], statsPeriod, (value) => {
      statsPeriod = value;
      loadStats();
    }),
    statsButtons("Scala", [["absolute", "Assoluti"], ["relative", "Percentuali"]], statsRelative ? "relative" : "absolute", (value) => {
      statsRelative = value === "relative";
      renderStats(root.getAttribute("aria-busy") === "true");
    }),
  );
  header.append(filters);
  root.replaceChildren(header);
  if (loading && !statsData) {
    const status = element("p", "stats-note", "Caricamento statistiche…");
    status.setAttribute("role", "status");
    root.append(status);
    return;
  }
  if (!statsData) return;
  const data = statsData;
  const summary = element("div", "stats-group");
  summary.append(
    figure(`${data.words_guessed}/${data.words}`, "parole"),
    figure(`${data.correct_attempts}/${data.attempts}`, "tentativi"),
  );
  root.append(summary);
  if (data.warnings.length) {
    const warning = element("p", "stats-note", "Alcuni record della cronologia non sono leggibili e sono stati esclusi. I totali potrebbero essere incompleti.");
    warning.setAttribute("role", "status");
    root.append(warning);
  }
  const chart = element("div", "word-chart");
  chart.setAttribute("role", "list");
  chart.setAttribute("aria-label", "Risultati per verbo");
  const chartRows = new Map();
  chart.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-sort]");
    if (!button) return;
    statsSort = button.dataset.sort;
    chart.replaceChildren(...sortedStatsRows(data.per_word, statsSort).map((row) => chartRows.get(row)));
    button.focus({preventScroll: true});
  });
  const maximum = Math.max(1, ...data.per_word.map((row) => row.wrong + row.almost + row.correct));
  for (const row of sortedStatsRows(data.per_word, statsSort)) {
    const total = row.wrong + row.almost + row.correct;
    const item = element("div", "word-row");
    item.setAttribute("role", "listitem");
    const popularity = row.popularity === null ? "—" : row.popularity.toFixed(2) + (row.provisional ? "*" : "");
    const description = `${row.word}: ${row.wrong} errate, ${row.almost} quasi corrette, ${row.correct} corrette. Totale ${total} frasi. Tentativi ${row.attempts}. Popolarità ${popularity}.`;
    item.setAttribute("aria-label", description);
    item.title = description;
    const word = statsSortButton("word-label", "word", `${row.word} · Ordina alfabeticamente`, row.word);
    word.lang = "de";
    const plot = statsSortButton("word-bar", "attempts", `Ordina per tentativi · ${row.attempts} tentativi`);
    const bar = element("span", "word-bar-fill");
    bar.setAttribute("aria-hidden", "true");
    plot.append(bar);
    for (const [kind, label] of [["wrong", "Errate"], ["almost", "Quasi corrette"], ["correct", "Corrette"]]) {
      const segment = element("span", `bar-segment bar-${kind}`);
      segment.style.width = `${100 * row[kind] / (statsRelative ? total || 1 : maximum)}%`;
      segment.title = `${label}: ${row[kind]} (${total ? Math.round(100 * row[kind] / total) : 0}%)`;
      bar.append(segment);
      if (row[kind] > 0) {
        const value = element("span", `bar-value bar-value-${kind}`,
          statsRelative ? `${Math.round(100 * row[kind] / total)}%` : String(row[kind]));
        value.setAttribute("aria-hidden", "true");
        segment.append(value);
      }
    }
    item.append(word, plot, statsSortButton("word-popularity", "popularity", `Ordina per popolarità · ${popularity}`, popularity));
    chartRows.set(row, item);
    chart.append(item);
  }
  root.append(chart);
}

async function loadStats() {
  const request = ++statsRequest;
  const root = $("stats");
  notify("error", "");
  const updatePeriod = () => {
    for (const button of root.querySelectorAll('.stats-options[aria-label="Periodo"] button')) {
      button.setAttribute("aria-pressed", String(button.dataset.value === statsPeriod));
    }
  };
  // Keep the current chart (and page height) intact until its replacement is ready.
  if (statsData) {
    root.setAttribute("aria-busy", "true");
    updatePeriod();
  } else {
    renderStats(true);
  }
  try {
    const data = await api(`/api/stats?period=${statsPeriod}`, undefined, false);
    if (view !== "stats" || request !== statsRequest) return;
    statsData = data;
    renderStats();
  } catch (error) {
    if (view !== "stats" || request !== statsRequest) return;
    root.setAttribute("aria-busy", "false");
    if (statsData) {
      statsPeriod = statsData.period;
      updatePeriod();
    } else {
      renderStats();
    }
    notify("error", error.message);
  }
}

async function openStats() {
  view = "stats";
  show();
  await loadStats();
}

// A match is addressable as {base}game/{lives}-{randomness}-{seed}, so the same
// link replays the same sentence order locally and on the static site.
const GAME_URL = /\/game\/(\d+)-(\d+(?:\.\d+)?)-(\d+)\/?$/;

function appBase() {
  return location.pathname.replace(/game\/[^/]*\/?$/, "").replace(/[^/]*$/, "");
}

function urlGame() {
  const match = location.pathname.match(GAME_URL);
  if (!match) return null;
  const [lives, randomness, seed] = match.slice(1).map(Number);
  if (!Number.isSafeInteger(lives) || lives < 1 || !(randomness <= 2) || !Number.isSafeInteger(seed) || seed > 0xFFFFFFFF) {
    return undefined;
  }
  return {lives, randomness, seed};
}

function gameHref(game) {
  return `${appBase()}game/${game.initial_lives}-${game.randomness}-${game.seed}`;
}

function sameGame(game, wanted) {
  return Boolean(game) && game.initial_lives === wanted.lives && game.randomness === wanted.randomness &&
    game.seed === wanted.seed;
}

function setUrl(href) {
  if (location.pathname !== href) history.pushState(null, "", href);
}

function prefillSettings({lives, randomness}) {
  $("game-lives").value = String(lives);
  $("game-randomness").value = String(randomness);
  showRandomness();
}

function showSetup() {
  setUrl(appBase());
  view = "setup";
  notify("error", "");
  notify("notice", "");
  notify("warnings", "");
  show();
}

const SVG_NS = "http://www.w3.org/2000/svg";
const HEART_PATH = "M 65,29 C 59,19 49,12 37,12 20,12 7,25 7,42 7,75 25,80 65,118 105,80 123,75 123,42 123,25 110,12 93,12 81,12 71,19 65,29 z";

function renderHearts(game, lostLife) {
  const hearts = $("game-hearts");
  const spent = game.initial_lives - game.lives_left;
  function heart(lost, animated) {
    // Heart shape from "Heart corazón.svg" by Fibonacci / derivative work by Pengo,
    // Wikimedia Commons, CC BY-SA 3.0: https://commons.wikimedia.org/wiki/File:Heart_coraz%C3%B3n.svg
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "7 12 116 106");
    svg.setAttribute("focusable", "false");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", HEART_PATH);
    svg.append(path);
    const icon = element("span", "game-heart");
    icon.append(svg);
    icon.classList.toggle("spent", lost);
    icon.classList.toggle("just-spent", animated);
    return icon;
  }
  hearts.replaceChildren();
  if (game.initial_lives <= 12) {
    for (let i = 0; i < game.initial_lives; i++) {
      hearts.append(heart(i >= game.lives_left, lostLife && i === game.lives_left));
    }
  } else {
    if (game.lives_left) hearts.append(heart(false, false), element("span", "", `×${game.lives_left}`));
    if (spent) hearts.append(heart(true, lostLife), element("span", "", `×${spent}`));
  }
  $("game-life-status").textContent = `Vite rimaste: ${game.lives_left} su ${game.initial_lives}`;
}

function render(next, scroll = false) {
  const previousLives = state?.game?.lives_left;
  state = next;

  const trail = document.createDocumentFragment();
  for (const [position, previous] of [...state.trail].reverse().entries()) {
    const row = element("article", "previous");
    row.append(element("span", "past-number", String(previous.number).padStart(2, "0")));
    const sentences = element("div", "past-sentences");
    const translation = element("p", "translation");
    translation.lang = "de";
    translation.append(highlighted(previous.german, previous.german_target));
    sentences.append(translation);
    const italian = element("p", "past-italian");
    italian.lang = "it";
    italian.append(highlighted(previous.italian, previous.italian_target));
    sentences.append(italian);
    row.append(sentences);
    const trials = element("div", "past-trials");
    const attempts = element("div", "attempts");
    attempts.append(historyView(previous, !staticGame && position === 0 && (!state.ended || Boolean(state.game.result))));
    trials.append(attempts);
    row.append(trials);
    trail.append(row);
  }
  $("trail").replaceChildren(trail);
  const current = state.current;
  const game = state.game;
  $("game-progress").textContent = `${state.trail.length + Number(Boolean(current) && !state.ended)}/${game.total}`;
  renderHearts(game, scroll && previousLives > game.lives_left);
  $("end-title").textContent = game.result === "won" ? "Partita completata." :
    game.result === "lost" ? "Vite esaurite." : "Partita terminata.";
  $("end-summary").textContent = `${state.correct}/${game.total} frasi risolte · ${state.trail.length - state.correct} saltate`;
  show();
  if (current) {
    $("exercise-number").textContent = String(current.number).padStart(2, "0");
    $("prompt").replaceChildren(highlighted(current.italian, current.italian_target));
    $("attempts").replaceChildren(attemptsView(current.attempts));
  }
  if (state.fatal_error) notify("error", state.fatal_error);
  controls();
  if (scroll) {
    const destination = state.ended ? $("session-end") : $("exercise");
    if (destination.getBoundingClientRect().bottom > window.innerHeight || destination.getBoundingClientRect().top < 0) {
      destination.scrollIntoView({behavior: "auto", block: "start"});
    }
  }
}

async function api(path, payload, authenticate = true) {
  if (staticGame) return staticGame.request(path, payload);
  const headers = {};
  if (authenticate && token) headers["X-Deutsch-Session"] = token;
  const options = {headers, cache: "no-store"};
  if (payload !== undefined) {
    options.method = "POST";
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (_) {
    throw new Error("Server locale non raggiungibile. Controlla il terminale e riprova: la risposta resta nel campo.");
  }
  const data = await response.json();
  if (!response.ok) {
    if (data.state) render(data.state);
    const error = new Error(data.error || "Richiesta non riuscita.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function setBusy(value) {
  busy = value;
  $("answer-form").setAttribute("aria-busy", String(value));
  controls();
}

async function submit(raw, flagAttempt, unflag = false) {
  if (busy || !state || (state.ended && (flagAttempt === undefined || !state.game.result))) return;
  const presentation = state.ended ? state.trail.at(-1).presentation_id : state.current.presentation_id;
  // Retrying after a lost response reuses the request ID. The server will not
  // log the same answer twice or apply it to the next exercise.
  if (!pending || pending.guess !== raw || pending.flag_attempt !== flagAttempt || Boolean(pending.unflag) !== unflag || pending.presentation_id !== presentation) {
    pending = {guess: raw, presentation_id: presentation, request_id: crypto.randomUUID()};
    if (flagAttempt !== undefined) pending.flag_attempt = flagAttempt;
    if (unflag) pending.unflag = true;
  }
  setBusy(true);
  notify("error", "");
  notify("notice", "");
  try {
    const response = await api("/api/submit", pending);
    pending = null;
    $("answer").value = "";
    const changed = flagAttempt === undefined && response.state.current?.presentation_id !== presentation;
    render(response.state, changed);
    // A flag toggle is acknowledged by the flag itself, not by a notice.
    if (response.message && flagAttempt === undefined) notify("notice", response.message.text);
  } catch (error) {
    notify("error", error.message);
    if (error.status === 409) {
      try {
        const response = await api("/api/state");
        render(response.state);
        if (response.state.current?.presentation_id !== presentation) $("answer").value = "";
        pending = null;
      } catch (_) { /* Preserve the original error and typed input. */ }
    } else if (error.status) {
      // A server-side failure is known; a fresh user retry may retry a failed
      // disk write. Only ambiguous network failures need the same request ID.
      pending = null;
    }
  } finally {
    setBusy(false);
    if (!state.ended) $("answer").focus({preventScroll: true});
  }
}

async function start(options) {
  if (busy) return;
  setBusy(true);
  notify("error", "");
  notify("notice", "");
  try {
    // A rejected start leaves the current session available to resume.
    let request = storage?.getItem("deutsch.start");
    request = request ? JSON.parse(request) : null;
    if (!request || Object.hasOwn(request, "mode") || request.lives !== options.lives ||
        request.randomness !== options.randomness || request.seed !== options.seed) {
      request = {...options, request_id: crypto.randomUUID()};
    }
    storage?.setItem("deutsch.start", JSON.stringify(request));
    const started = await api("/api/start", request, false);
    // The old session is ended without rendering it, so its "session ended"
    // screen does not flash before the new session appears.
    if (!staticGame && state && !state.ended) {
      try {
        const response = await api("/api/submit", {guess: "/q", presentation_id: state.current.presentation_id, request_id: crypto.randomUUID()});
        state = response.state;
      } catch (error) {
        if (error.status !== 409) throw error;
        const response = await api("/api/state");
        state = response.state;
        if (!state.ended) {
          const stopped = await api("/api/submit", {guess: "/q", presentation_id: state.current.presentation_id, request_id: crypto.randomUUID()});
          state = stopped.state;
        }
      }
    }
    token = started.token;
    storage?.setItem("deutsch.session", token);
    storage?.removeItem("deutsch.start");
    pending = null;
    $("answer").value = "";
    view = "practice";
    render(started.state);
    setUrl(gameHref(started.state.game));
  } catch (error) {
    if (state) render(state);
    notify("error", error.message);
  } finally {
    setBusy(false);
    if (view === "practice" && state && !state.ended) $("answer").focus({preventScroll: true});
  }
}

$("answer-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit($("answer").value);
});
$("game-skip").addEventListener("click", () => submit(""));
$("trail").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-attempt]");
  if (button) submit("", Number(button.dataset.attempt), button.dataset.unflag !== undefined);
});
$("play-tab").addEventListener("click", showSetup);
$("stats-tab")?.addEventListener("click", () => { if (view !== "stats") openStats(); });
$("resume").addEventListener("click", () => {
  view = "practice";
  render(state);
  setUrl(gameHref(state.game));
  if (!state.ended) $("answer").focus({preventScroll: true});
});
$("restart").addEventListener("click", showSetup);
function showRandomness() {
  const slider = $("game-randomness");
  const min = Number(slider.min), max = Number(slider.max);
  slider.style.setProperty("--fill", `${((slider.valueAsNumber - min) / (max - min)) * 100}%`);
  $("game-randomness-value").value = slider.valueAsNumber.toFixed(2);
}
$("game-randomness").addEventListener("input", showRandomness);
showRandomness();
$("game-settings").addEventListener("submit", (event) => {
  event.preventDefault();
  start({
    lives: $("game-lives").valueAsNumber,
    randomness: $("game-randomness").valueAsNumber,
  });
});

// Open the match named by the URL: resume it if it is the current one,
// otherwise start it (ending any other active match first).
async function openUrlGame(wanted) {
  if (wanted === undefined) {
    view = "setup";
    show();
    notify("error", "Link della partita non valido.");
    return;
  }
  if (state && sameGame(state.game, wanted)) {
    view = "practice";
    render(state);
    if (!state.ended) $("answer").focus({preventScroll: true});
    return;
  }
  prefillSettings(wanted);
  await start(wanted);
  if (view !== "practice") show();
}

async function initialize() {
  try {
    controls();
    const wanted = urlGame();
    if (token) {
      try {
        const response = await api("/api/state");
        if (wanted !== null) {
          state = response.state;
          await openUrlGame(wanted);
          return;
        }
        view = "practice";
        render(response.state);
        history.replaceState(null, "", gameHref(response.state.game));
        $("answer").focus({preventScroll: true});
        return;
      } catch (error) {
        if (error.status !== 404) throw error;
        token = null;
        storage?.removeItem("deutsch.session");
      }
    }
    if (wanted !== null) {
      await openUrlGame(wanted);
      return;
    }
    show();
  } catch (error) {
    notify("error", error.message);
  }
}

window.addEventListener("popstate", () => {
  if (busy) return;
  const wanted = urlGame();
  if (wanted === null) {
    view = "setup";
    notify("error", "");
    notify("notice", "");
    show();
  } else {
    openUrlGame(wanted);
  }
});
initialize();
