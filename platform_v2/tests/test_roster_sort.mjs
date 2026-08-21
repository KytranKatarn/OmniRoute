// NULL is not zero. An unscored agent must never rank as the worst performer.
import { readFileSync } from 'node:fs';
import { strict as assert } from 'node:assert';
import test from 'node:test';

const src = readFileSync(
  new URL('../tools/department_hq/static/js/roster_sort.js', import.meta.url), 'utf8');
const { sortAgents, groupAgents } =
  new Function(src + '; return { sortAgents, groupAgents };')();

const AGENTS = [
  { id: 1, name: 'A', performance_score: 0.9, department: 'Eng' },
  { id: 2, name: 'B', performance_score: null, department: 'Eng' },
  { id: 3, name: 'C', performance_score: 0.2, department: 'Ops' },
];

test('nulls sort last ascending', () => {
  const ids = sortAgents(AGENTS, 'performance_score', 'asc').map(a => a.id);
  assert.deepEqual(ids, [3, 1, 2]);
});

test('nulls sort last DESCENDING too', () => {
  const ids = sortAgents(AGENTS, 'performance_score', 'desc').map(a => a.id);
  assert.deepEqual(ids, [1, 3, 2]);
});

test('null is not treated as zero', () => {
  const ids = sortAgents(AGENTS, 'performance_score', 'asc').map(a => a.id);
  assert.notEqual(ids[0], 2, 'unscored agent ranked as worst — NULL coerced to 0');
});

test('grouping keeps every agent exactly once', () => {
  const groups = groupAgents(AGENTS, 'department');
  const total = Object.values(groups).reduce((n, g) => n + g.length, 0);
  assert.equal(total, AGENTS.length);
});

// The API serializes DECIMAL columns (performance_score, success_rate) as
// JSON strings, not numbers (psycopg2 Decimal -> JSON string). A lexicographic
// comparator puts "100.00" before "5.50" ascending — the exact live bug
// (KB: sorting ascending by performance_score never surfaced the true worst
// performer, 5.5, because "100.00" < "5.50" < "99.98" as strings).
const NUMERIC_STRING_AGENTS = [
  { id: 10, name: 'Perfect', performance_score: '100.00', department: 'Eng' },
  { id: 11, name: 'Great', performance_score: '99.98', department: 'Eng' },
  { id: 12, name: 'Worst', performance_score: '5.50', department: 'Ops' },
];

test('numeric STRINGS sort numerically, not lexicographically', () => {
  const asc = sortAgents(NUMERIC_STRING_AGENTS, 'performance_score', 'asc').map(a => a.id);
  assert.deepEqual(asc, [12, 11, 10], 'ascending must put "5.50" first, not "100.00"');

  const desc = sortAgents(NUMERIC_STRING_AGENTS, 'performance_score', 'desc').map(a => a.id);
  assert.deepEqual(desc, [10, 11, 12], 'descending must put "100.00" first');
});

test('NULL still sorts last in both directions when values are numeric strings', () => {
  const withNull = [
    { id: 20, name: 'A', performance_score: '100.00' },
    { id: 21, name: 'B', performance_score: null },
    { id: 22, name: 'C', performance_score: '5.50' },
  ];
  assert.deepEqual(
    sortAgents(withNull, 'performance_score', 'asc').map(a => a.id), [22, 20, 21]);
  assert.deepEqual(
    sortAgents(withNull, 'performance_score', 'desc').map(a => a.id), [20, 22, 21]);
});

test('text columns still sort alphabetically, not numerically', () => {
  const byName = [
    { id: 30, name: 'F.O.R.G.E.', department: 'Engineering' },
    { id: 31, name: 'A.R.C.H.I.E.', department: 'Executive' },
    { id: 32, name: 'V.I.G.I.L.', department: 'Security' },
  ];
  assert.deepEqual(
    sortAgents(byName, 'name', 'asc').map(a => a.id), [31, 30, 32],
    'names must sort alphabetically (A < F < V)');

  const byDept = [
    { id: 40, name: 'X', department: 'Zebra Dept' },
    { id: 41, name: 'Y', department: 'Alpha Dept' },
  ];
  assert.deepEqual(
    sortAgents(byDept, 'department', 'asc').map(a => a.id), [41, 40],
    'departments must sort alphabetically, not be coerced numeric');
});
