/* Client-only transport for the static export. No storage or API calls. */
"use strict";

(() => {
  const {cards, alphabet} = globalThis.DeutschDeck;
  delete globalThis.DeutschDeck;
  const encoder = new TextEncoder();
  let game = null;
  let pendingReveal = null;

  // Bit-for-bit identical to mulberry32 in deutsch/difficulty.py, so a shared
  // /game/{lives}-{randomness}-{seed} link gives the same order everywhere.
  function mulberry32(seed) {
    let state = seed >>> 0;
    return () => {
      state = (state + 0x6D2B79F5) >>> 0;
      let t = Math.imul(state ^ (state >>> 15), state | 1);
      t = (t + Math.imul(t ^ (t >>> 7), t | 61)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Mirrors ordered_exercises in deutsch/difficulty.py: ranked cards by noisy
  // difficulty, unranked ones last in deck order; noise only for ranked cards.
  function orderedCards(cards, randomness, seed) {
    const random = mulberry32(seed);
    return cards.map((card) => ({card, priority: card.difficulty === null ? Infinity : card.difficulty +
      (randomness ? randomness * Math.log(-Math.log(Math.max(random(), 2 ** -53))) : 0)}))
      .sort((a, b) => a.priority - b.priority).map(({card}) => card);
  }

  const normalize = (text) => text.trim().toLowerCase().normalize("NFC").replaceAll("ß", "ss");

  async function digest(key, guess) {
    const buffer = await crypto.subtle.digest("SHA-256", encoder.encode(`${key}:${guess}`));
    return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  function* oneEdit(guess, length) {
    const chars = Array.from(guess);
    if (chars.length > length + 1 || chars.length < length - 1) return;
    for (let i = 0; i <= chars.length; i++) {
      const left = chars.slice(0, i).join("");
      if (chars.length === length - 1) {
        const right = chars.slice(i).join("");
        for (const letter of alphabet) yield `${left}${letter}${right}`;
      } else if (i < chars.length) {
        const right = chars.slice(i + 1).join("");
        if (chars.length > length) yield left + right;
        else for (const letter of alphabet) if (letter !== chars[i]) yield `${left}${letter}${right}`;
      }
    }
  }

  async function evaluate(card, raw) {
    if (!crypto.subtle) throw new Error("Apri il gioco tramite HTTPS o localhost.");
    const guess = normalize(raw);
    const hashed = await digest(card.key, guess);
    if (hashed === card.target) return "correct";
    if (card.alternatives.includes(hashed)) return "valid_alternative";
    const edits = new Set(oneEdit(guess, card.length));
    const neighbors = await Promise.all([...edits].map((variant) => digest(card.key, variant)));
    return neighbors.includes(card.target) ? "almost_there" : "incorrect";
  }

  function state() {
    const {current, trail, correct, guesses, ended, initial_lives, lives_left, total, result, randomness, seed} = game;
    return {current: current && {...current, attempts: [...current.attempts]}, trail: [...trail], correct, guesses, ended,
      fatal_error: null, game: {initial_lives, lives_left, total, result, randomness, seed}};
  }

  function nextCard() {
    const card = game.deck[game.trail.length];
    if (!card) {
      game.ended = true;
      game.result = "won";
      return;
    }
    game.card = card;
    game.current = {presentation_id: crypto.randomUUID(), number: game.trail.length + 1, italian: card.italian,
      italian_target: card.italian_target, attempts: []};
  }

  function start({lives, randomness = 0, seed}) {
    if (seed === undefined || seed === null) seed = crypto.getRandomValues(new Uint32Array(1))[0];
    if (!Number.isSafeInteger(lives) || lives < 1 || !(randomness >= 0 && randomness <= 2) ||
        !Number.isInteger(seed) || seed < 0 || seed > 0xFFFFFFFF) {
      throw new Error("Impostazioni di gioco non valide.");
    }
    const deck = orderedCards(cards, randomness, seed);
    game = {deck, total: deck.length, current: null, trail: [], correct: 0, guesses: 0, ended: false,
      result: null, initial_lives: lives, lives_left: lives, randomness, seed};
    nextCard();
    return {state: state()};
  }

  // Load only the translation being revealed, not the answers for upcoming prompts.
  function getAnswer(card) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      let answer = null;
      pendingReveal = {key: card.key, receive: (data) => { answer = data; }};
      script.src = `answers/${card.key}.js`;
      const finish = () => {
        pendingReveal = null;
        script.remove();
        if (answer) resolve(answer);
        else reject(new Error("Impossibile caricare la traduzione. Riprova."));
      };
      script.onload = script.onerror = finish;
      document.head.append(script);
    });
  }

  async function submit({guess, presentation_id}) {
    if (game.ended || game.current.presentation_id !== presentation_id) throw new Error("Esercizio non più attivo.");
    if (["/q", "/quit"].includes(guess.trim().toLowerCase())) {
      game.current = null;
      game.ended = true;
      return {state: state()};
    }
    const result = guess === "" ? null : await evaluate(game.card, guess);
    const finished = result === null || result === "correct";
    const answer = finished ? await getAnswer(game.card) : null;
    if (result) {
      game.current.attempts.push({guess, result});
      if (result !== "valid_alternative") game.guesses++;
    }
    if (finished) {
      if (result === "correct") game.correct++;
      else game.lives_left--;
      game.trail.push({...game.current, ...answer, difficulty: game.card.difficulty,
        outcome: result === "correct" ? "completed" : "gave_up"});
      game.current = null;
      if (!game.lives_left) {
        game.result = "lost";
        game.ended = true;
      } else nextCard();
    }
    return {state: state()};
  }

  globalThis.DeutschStatic = {
    async request(path, payload) {
      if (path === "/api/start") return start(payload);
      if (path === "/api/submit") return submit(payload);
      throw new Error("Funzione non disponibile nella versione statica.");
    },
    reveal(key, data) {
      if (pendingReveal?.key === key) pendingReveal.receive(data);
    },
  };
})();
