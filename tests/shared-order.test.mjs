import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

// Same reference sequence as MULBERRY32_REFERENCE in tests/test_web.py: a
// /game/{lives}-{randomness}-{seed} link must order sentences identically in
// the local server (Python) and the static site (this file).
const source = readFileSync(new URL('../deutsch/static/static-game.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('function mulberry32('), source.indexOf('const normalize')), context);

test('mulberry32 matches the Python reference sequence', () => {
  const reference = {
    0: [0.26642920868471265, 0.0003297457005828619, 0.2232720274478197, 0.1462021479383111],
    42: [0.6011037519201636, 0.44829055899754167, 0.8524657934904099, 0.6697340414393693],
    4294967295: [0.8964226141106337, 0.189478256739676, 0.7156526781618595, 0.9440599093213677],
  };
  for (const [seed, expected] of Object.entries(reference)) {
    const random = context.mulberry32(Number(seed));
    assert.deepEqual(expected.map(() => random()), expected);
  }
});

test('orderedCards is deterministic per seed and keeps unranked cards last', () => {
  const cards = Array.from({length: 8}, (_, i) => ({key: String(i), difficulty: i === 7 ? null : i * 0.1}));
  const keys = (randomness, seed) => Array.from(context.orderedCards(cards, randomness, seed), (card) => card.key);
  assert.deepEqual(keys(0, 1), ['0', '1', '2', '3', '4', '5', '6', '7']);
  assert.deepEqual(keys(0.3, 7), keys(0.3, 7));
  assert.equal(keys(0.3, 7).at(-1), '7');
  assert.ok(Array.from({length: 20}, (_, seed) => keys(0.3, seed).join()).some((order) => order !== keys(0.3, 7).join()));
});
