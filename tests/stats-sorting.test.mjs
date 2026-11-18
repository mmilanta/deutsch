import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../deutsch/static/app.js', import.meta.url), 'utf8');
const sorting = source.slice(source.indexOf('function sortedStatsRows('), source.indexOf('\nfunction statsSortButton('));
const context = vm.createContext({});
vm.runInContext(sorting, context);
const rows = [
  {word: 'gehen', attempts: 5, popularity: 5.8},
  {word: 'arbeiten', attempts: 2, popularity: 5.6},
  {word: 'heißen', attempts: 5, popularity: null},
  {word: 'abbauen', attempts: 0, popularity: 0},
];
const words = sort => Array.from(context.sortedStatsRows(rows, sort), row => row.word);

test('word column orders alphabetically', () => {
  assert.deepEqual(words('word'), ['abbauen', 'arbeiten', 'gehen', 'heißen']);
});
test('bar column orders most attempts first, with alphabetical ties', () => {
  assert.deepEqual(words('attempts'), ['gehen', 'heißen', 'arbeiten', 'abbauen']);
});
test('popularity column orders highest first and missing estimates last', () => {
  assert.deepEqual(words('popularity'), ['gehen', 'arbeiten', 'abbauen', 'heißen']);
});
test('sorting preserves source order for later range or scale changes', () => {
  words('word');
  assert.deepEqual(rows.map(row => row.word), ['gehen', 'arbeiten', 'heißen', 'abbauen']);
  assert.equal(context.sortedStatsRows([], 'popularity').length, 0);
});
