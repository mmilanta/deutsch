"use strict";

const $ = (id) => document.getElementById(id);
const modeButtons = [...document.querySelectorAll("[data-mode]")];
const labels = {
  correct: "Corretto.",
  almost_there: "Quasi.",
  incorrect: "Non ancora.",
};
let config = null;
let state = null;
let token = sessionStorage.getItem("deutsch.session");
let busy = false;
let pending = null;
let view = "practice";
localStorage.removeItem("deutsch.palette"); // left behind by the removed palette picker

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

// A completed sentence: one row per wrong guess, then the solution, green
// if it was guessed and red if it was revealed. Pressing a wrong guess of
// the latest sentence flags it as a valid synonym for that sentence only;
// pressing the flag withdraws it.
function historyView(previous, flaggable) {
  const fragment = document.createDocumentFragment();
  for (const [index, attempt] of previous.attempts.entries()) {
    if (attempt.result === "correct") continue;
    const canFlag = flaggable && !attempt.flagged;
    const row = element(canFlag ? "button" : "p", "attempt");
    if (canFlag) {
      row.type = "button";
      row.dataset.attempt = String(index + 1);
      row.title = "Segnala come sinonimo";
    }
    row.append(element("span", "typed", attempt.guess));
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
  // Popularity is the verb's Zipf frequency; absent without frequency data.
  if (typeof previous.popularity === "number") {
    const popularity = element("span", "popularity", previous.popularity.toFixed(2));
    popularity.title = "Popolarità (frequenza Zipf)";
    solution.append(popularity);
  }
  fragment.append(solution);
  return fragment;
}

function notify(id, text) {
  $(id).textContent = text || "";
  $(id).hidden = !text;
}

function controls() {
  const active = state && !state.ended;
  for (const id of ["answer", "submit-answer"]) {
    $(id).disabled = busy || !active;
  }
  $("restart").disabled = busy;
  for (const button of modeButtons) {
    button.disabled = busy || !config || !config.modes.includes(button.dataset.mode);
  }
}

// The Stats tab replaces the practice view; the session keeps running.
function show() {
  const stats = view === "stats";
  for (const button of modeButtons) {
    button.setAttribute("aria-pressed", String(!stats && button.dataset.mode === state?.mode));
  }
  $("stats-tab").setAttribute("aria-pressed", String(stats));
  $("stats").hidden = !stats;
  $("trail").hidden = stats;
  $("exercise").hidden = stats || !state?.current || state.ended;
  $("session-end").hidden = stats || !state?.ended;
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

function closeStats() {
  view = "practice";
  show();
  if (state && !state.ended) $("answer").focus({preventScroll: true});
}

function render(next, scroll = false) {
  state = next;
  notify("warnings", state.warnings.length ? state.warnings.join(" · ") : "");

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
    attempts.append(historyView(previous, position === 0 && !state.ended));
    trials.append(attempts);
    row.append(trials);
    trail.append(row);
  }
  $("trail").replaceChildren(trail);
  const current = state.current;
  show();
  if (current) {
    $("exercise-number").textContent = String(current.number).padStart(2, "0");
    $("prompt").replaceChildren(highlighted(current.italian, current.italian_target));
    $("attempts").replaceChildren(attemptsView(current.attempts));
    $("explanation").textContent = current.explanation || "";
    $("explanation").hidden = !current.explanation;
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
  if (busy || !state || state.ended) return;
  const presentation = state.current.presentation_id;
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
    const changed = response.state.current?.presentation_id !== presentation;
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

async function start(mode) {
  if (busy) return;
  setBusy(true);
  notify("error", "");
  notify("notice", "");
  try {
    // The old session is ended without rendering it, so its "session ended"
    // screen does not flash before the new session appears.
    if (state && !state.ended) {
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
    // Keep this ID after a network failure so clicking again doesn't open
    // duplicate sessions if the response, rather than the request, was lost.
    let request = sessionStorage.getItem("deutsch.start");
    request = request ? JSON.parse(request) : null;
    if (!request || request.mode !== mode) request = {mode, request_id: crypto.randomUUID()};
    sessionStorage.setItem("deutsch.start", JSON.stringify(request));
    const response = await api("/api/start", request, false);
    token = response.token;
    sessionStorage.setItem("deutsch.session", token);
    sessionStorage.removeItem("deutsch.start");
    pending = null;
    $("answer").value = "";
    render(response.state);
  } catch (error) {
    if (state) render(state);
    notify("error", error.message);
  } finally {
    setBusy(false);
    if (state && !state.ended) $("answer").focus({preventScroll: true});
  }
}

$("answer-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit($("answer").value);
});
$("trail").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-attempt]");
  if (button && !busy && state && !state.ended) submit("", Number(button.dataset.attempt), button.dataset.unflag !== undefined);
});
$("stats-tab").addEventListener("click", () => (view === "stats" ? closeStats() : openStats()));
$("restart").addEventListener("click", () => start(state?.mode || config.default_mode));
for (const button of modeButtons) {
  button.addEventListener("click", () => {
    if (view === "stats") closeStats();
    if (button.dataset.mode !== state?.mode || state?.ended) start(button.dataset.mode);
  });
}

async function initialize() {
  try {
    config = await api("/api/config", undefined, false);
    controls();
    if (token) {
      try {
        const response = await api("/api/state");
        render(response.state);
        $("answer").focus({preventScroll: true});
        return;
      } catch (error) {
        if (error.status !== 404) throw error;
        token = null;
        sessionStorage.removeItem("deutsch.session");
      }
    }
    await start(config.default_mode);
  } catch (error) {
    notify("error", error.message);
  }
}
initialize();
