import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { nodeFacts } from '../src/app.js';

test('карточка охватывает все поля расчёта роли для выбранного gid', () => {
  const columns = readFileSync(new URL('../deliverables/nodes_roles.csv', import.meta.url), 'utf8')
    .split(/\r?\n/, 1)[0].split(',');
  const alreadyVisible = new Set(['gid', 'role', 'role_score', 'cluster_id', 'priority_score', 'evidence']);
  const facts = nodeFacts(Object.fromEntries(columns.map((column) => [column, column === 'gid' ? '100000003115284100' : 0])));
  const covered = new Set([...alreadyVisible, ...facts.map((fact) => fact.key)]);
  assert.deepEqual(columns.filter((column) => !covered.has(column)), []);
  assert.ok(facts.every((fact) => fact.label && fact.value !== undefined));
});

test('нулевые и неполные показатели не превращаются в выдуманные значения', () => {
  const facts = nodeFacts({ in_tx: 0, out_tx: 4, active_days: 6 });
  assert.equal(facts.find((fact) => fact.key === 'in_tx')?.value, 0);
  assert.equal(facts.find((fact) => fact.key === 'out_tx')?.value, 4);
  assert.equal(facts.find((fact) => fact.key === 'active_days')?.value, 6);
  assert.equal(facts.find((fact) => fact.key === 'pagerank')?.value, undefined);
});
