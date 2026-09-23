import test from 'node:test';
import assert from 'node:assert/strict';
import { buildAssistantContext } from '../src/assistant-context.mjs';

const id = (number) => `10000000000000${String(number).padStart(4, '0')}`;
const node = (number, priority = 0.5) => ({ gid: id(number), priority_score: priority, role: 'transit' });
const edge = (from, to) => ({ src: id(from), dst: id(to), sum_kzt: 10000, n_tx: 2 });
const network = {
  nodes: [node(1), node(2), node(3, .9), node(4), node(5)],
  edges: [edge(1, 3), edge(2, 4), edge(4, 3), edge(3, 5)],
};

test('common recipient is computed with exact directed witness paths', () => {
  const context = buildAssistantContext(`Кто собирает с ${id(1)} и ${id(2)}?`, network);
  assert.deepEqual(context.sources, [id(1), id(2)]);
  const candidate = context.common_recipients[0];
  assert.equal(candidate.gid, id(3));
  assert.equal(candidate.coverage, 2);
  assert.deepEqual(candidate.witnesses.map((item) => item.path), [[id(1), id(3)], [id(2), id(4), id(3)]]);
  const edgeKeys = new Set(context.edges.map((item) => `${item.src}:${item.dst}`));
  for (const witness of candidate.witnesses) {
    for (const item of witness.edges) assert.ok(edgeKeys.has(`${item.src}:${item.dst}`));
  }
});

test('separate source neighborhoods remain visible when there is no common recipient', () => {
  const input = {
    nodes: Array.from({ length: 6 }, (_, index) => node(index + 1)),
    edges: [edge(1, 3), edge(3, 5), edge(2, 4), edge(4, 6)],
  };
  const context = buildAssistantContext(`Проверь ${id(1)} и ${id(2)}`, input);
  assert.deepEqual(context.common_recipients, []);
  assert.ok(context.edges.some((item) => item.src === id(1) && item.dst === id(3)));
  assert.ok(context.edges.some((item) => item.src === id(4) && item.dst === id(6)));
});

test('unknown named GID never silently uses selected node or unrelated candidates', () => {
  const context = buildAssistantContext(`Проверь ${id(99)}`, network, id(1));
  assert.deepEqual(context.sources, []);
  assert.deepEqual(context.unknown_gids, [id(99)]);
  assert.deepEqual(context.nodes, []);
  assert.deepEqual(context.common_recipients, []);
  assert.equal(context.scope.selected_node_used, false);
  const selected = buildAssistantContext('Объясни этот узел', network, id(1));
  assert.deepEqual(selected.sources, [id(1)]);
  assert.equal(selected.scope.selected_node_used, true);
  assert.deepEqual(buildAssistantContext(`Номер 9${id(1)}99`, network).sources, []);
});

test('context bounds preserve witnesses and declare truncation', () => {
  const dense = { nodes: Array.from({ length: 90 }, (_, index) => node(index + 1)), edges: [] };
  for (let a = 1; a <= 90; a += 1) {
    for (let b = a + 1; b <= 90; b += 1) dense.edges.push(edge(a, b));
  }
  const context = buildAssistantContext(`Проверь ${id(1)} и ${id(2)}`, dense);
  assert.ok(context.nodes.length <= 60);
  assert.ok(context.edges.length <= 160);
  assert.equal(context.scope.context_is_partial, true);
  const included = new Set(context.nodes.map((item) => item.gid));
  assert.ok(context.edges.every((item) => included.has(item.src) && included.has(item.dst)));
  assert.ok(context.common_recipients.every((item) => included.has(item.gid)));
  assert.ok(context.common_recipients.every((item) => item.witnesses.every((w) => w.path.every((gid) => included.has(gid)))));
});

test('only known anonymized computed fields leave graph context', () => {
  const input = {
    nodes: [{ ...node(1), name: 'Secret Person', iin: '111111111111', api_key: 'secret',
      in_kzt: 12000, in_deg: 2, role_score: .8, evidence: '2 наблюдаемых входа',
      priority_factors: { role: .2, api_key: 'hidden' },
      optional: { cycle_count: 1, peer_outliers: ['входящий объём в верхнем 1%'], birthday: 'hidden' } }, node(2)],
    edges: [{ ...edge(1, 2), customer_name: 'hidden', transactions: [{ secret: true }] }],
    customer_records: [{ secret: true }],
  };
  const context = buildAssistantContext('Объясни', input, id(1));
  const record = context.nodes.find((item) => item.gid === id(1));
  assert.equal(record.in_kzt, 12000);
  assert.equal(record.in_deg, 2);
  assert.equal(record.out_kzt, undefined);
  assert.deepEqual(record.priority_factors, { role: .2 });
  assert.equal(record.optional.cycle_count, 1);
  assert.doesNotMatch(JSON.stringify(context), /Secret Person|hidden|birthday|api_key|customer_name|transactions|customer_records|111111111111/);
});

test('supplied dataset scope is bounded and retained without unrelated metadata or invented defaults', () => {
  const scope = 'July 2026, outgoing-only crawl, >=5000 KZT, max depth 4';
  const context = buildAssistantContext('Объясни ограничения', {
    ...network, meta: { scope, customer_name: 'Secret Meta', token: 'hidden-token' },
  }, id(1));
  assert.equal(context.scope.dataset_scope, scope);
  assert.doesNotMatch(JSON.stringify(context), /Secret Meta|hidden-token|customer_name/);
  const absent = buildAssistantContext('Объясни ограничения', network, id(1));
  assert.equal(Object.hasOwn(absent.scope, 'dataset_scope'), false);
  const long = buildAssistantContext('Объясни ограничения', { ...network, meta: { scope: 'x'.repeat(2000) } });
  assert.equal(long.scope.dataset_scope.length, 600);
});

test('cycles and repeated routes include real edge evidence and full-network resilience is labeled', () => {
  const input = {
    ...network, edges: [...network.edges, edge(3, 1)],
    optional: {
      cycles: [{ path: [id(1), id(3)] }, { path: [id(1), id(99)] }],
      repeated_routes: [{ path: [id(2), id(4), id(3)], matching_days: 2 }],
      resilience: { baseline_components: 1, remove_top: [{ n: 1, removed_gids: [id(3)], components: 2, largest_component: 2, largest_share_pct: 50 }] },
    },
  };
  const context = buildAssistantContext(`Покажи циклы и устойчивость ${id(1)}`, input);
  assert.deepEqual(context.optional.cycles.map((item) => item.path), [[id(1), id(3)]]);
  assert.equal(context.optional.resilience.scope, 'full_observed_network');
  assert.deepEqual(context.optional.resilience.remove_top[0].removed_gids, [id(3)]);
  assert.ok(context.edges.some((item) => item.src === id(3) && item.dst === id(1)));
});
