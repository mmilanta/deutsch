import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../deutsch/static/app.js', import.meta.url), 'utf8');
const loader = source.slice(source.indexOf('async function loadStats()'), source.indexOf('\nasync function openStats()'));

// Test the real async loader with delayed HTTP responses. Rendering is a spy:
// these checks protect state and request order, not browser layout or painting.
function setup(data = {period: 'all'}) {
  const requests = [];
  const renders = [];
  const notices = [];
  const buttons = ['all', 'year', 'month', 'day'].map(value => ({
    dataset: {value},
    setAttribute(name, next) { this[name] = next; },
  }));
  const root = {
    setAttribute(name, value) { this[name] = value; },
    querySelectorAll() { return buttons; },
  };
  const context = vm.createContext({
    statsData: data, statsPeriod: 'month', statsRequest: 0, view: 'stats',
    $: () => root,
    notify: (...args) => notices.push(args),
    renderStats: loading => renders.push({loading, data: context.statsData}),
    api: path => new Promise((resolve, reject) => requests.push({path, resolve, reject})),
  });
  vm.runInContext(loader, context);
  return {context, requests, renders, notices, root, buttons};
}

test('changing period preserves the chart until the new data arrives', async () => {
  const previous = {period: 'all', words_guessed: 5};
  const state = setup(previous);
  const pending = state.context.loadStats();
  assert.equal(state.context.statsData, previous);
  assert.equal(state.renders.length, 0);
  assert.equal(state.root['aria-busy'], 'true');
  assert.equal(state.buttons[2]['aria-pressed'], 'true');
  const next = {period: 'month', words_guessed: 2};
  state.requests[0].resolve(next);
  await pending;
  assert.equal(state.renders.length, 1);
  assert.equal(state.renders[0].data, next);
});

test('a slower previous range cannot overwrite the latest selection', async () => {
  const state = setup();
  const first = state.context.loadStats();
  state.context.statsPeriod = 'day';
  const second = state.context.loadStats();
  const latest = {period: 'day'};
  state.requests[1].resolve(latest);
  await second;
  state.requests[0].resolve({period: 'month'});
  await first;
  assert.equal(state.context.statsData, latest);
  assert.equal(state.renders.length, 1);
});

test('a failed refresh retains the chart and restores its range label', async () => {
  const previous = {period: 'all'};
  const state = setup(previous);
  const pending = state.context.loadStats();
  state.requests[0].reject(new Error('offline'));
  await pending;
  assert.equal(state.context.statsData, previous);
  assert.equal(state.context.statsPeriod, 'all');
  assert.equal(state.buttons[0]['aria-pressed'], 'true');
  assert.equal(state.root['aria-busy'], 'false');
  assert.equal(state.renders.length, 0);
  assert.equal(state.notices.at(-1)[1], 'offline');
});

test('only the initial visit uses a loading placeholder', async () => {
  const state = setup(null);
  const pending = state.context.loadStats();
  assert.equal(state.renders.length, 1);
  assert.equal(state.renders[0].loading, true);
  state.requests[0].resolve({period: 'month'});
  await pending;
  assert.equal(state.renders.length, 2);
});
