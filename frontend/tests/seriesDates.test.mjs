import test from 'node:test';
import assert from 'node:assert/strict';
import {firstSeriesDate} from '../src/seriesDates.js';
test('range start is not treated as occurrence when its weekday is excluded',()=>{
  assert.equal(firstSeriesDate('2026-11-09','2026-11-20',[3]),'2026-11-12');
});
test('empty range does not search an unrelated date',()=>{
  assert.equal(firstSeriesDate('2026-11-09','2026-11-10',[3]),null);
  assert.equal(firstSeriesDate('2026-11-09','2026-11-20',[]),null);
});
