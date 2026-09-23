import test from 'node:test';
import assert from 'node:assert/strict';
import { buildAssistantContext } from '../src/assistant-context.mjs';

test('five exact GIDs share a recipient through complete directed witness paths', () => {
  // These adjacent IDs exceed Number.MAX_SAFE_INTEGER. Converting them to
  // numbers would merge sources before the common-recipient search runs.
  const sources = [
    '100000000000000001', '100000000000000002', '100000000000000003',
    '100000000000000004', '100000000000000005',
  ];
  const receiver = '100000000000000099';
  const sharedPayer = '100000000000000088';
  const graph = {
    nodes: [
      ...sources, '100000000000000011', '100000000000000012',
      '100000000000000013', receiver, sharedPayer,
    ].map((gid) => ({ gid, role: 'transit', priority_score: 0.5 })),
    edges: [
      ['100000000000000001', receiver],
      ['100000000000000002', '100000000000000011'],
      ['100000000000000011', receiver],
      ['100000000000000003', receiver],
      ['100000000000000004', '100000000000000012'],
      ['100000000000000012', receiver],
      ['100000000000000005', '100000000000000013'],
      ['100000000000000013', receiver],
      // A common incoming neighbor is not a recipient of these five sources.
      ...sources.map((gid) => [sharedPayer, gid]),
    ].map(([src, dst]) => ({ src, dst, sum_kzt: 10000, n_tx: 1 })),
  };

  const context = buildAssistantContext(
    `Найди общего получателя переводов от пяти клиентов: ${sources.join(', ')}.`, graph,
  );
  assert.deepEqual(context.sources, sources);
  assert.deepEqual(context.unknown_gids, []);
  assert.equal(context.scope.source_count_total, 5);
  assert.equal(context.scope.sources_truncated, false);
  assert.deepEqual(context.common_recipients.map((candidate) => candidate.gid), [receiver]);

  const candidate = context.common_recipients[0];
  assert.equal(candidate.coverage, 5);
  assert.equal(candidate.source_count, 5);
  assert.equal(candidate.witnesses_truncated, false);
  assert.deepEqual(candidate.witnesses.map((witness) => witness.source), sources);
  assert.deepEqual(candidate.witnesses.map((witness) => witness.path), [
    ['100000000000000001', '100000000000000099'],
    ['100000000000000002', '100000000000000011', '100000000000000099'],
    ['100000000000000003', '100000000000000099'],
    ['100000000000000004', '100000000000000012', '100000000000000099'],
    ['100000000000000005', '100000000000000013', '100000000000000099'],
  ]);

  const observedEdges = new Set(graph.edges.map((edge) => `${edge.src}:${edge.dst}`));
  const sentEdges = new Set(context.edges.map((edge) => `${edge.src}:${edge.dst}`));
  const sentGids = new Set(context.nodes.map((node) => node.gid));
  for (const gid of [...sources, receiver]) assert.ok(sentGids.has(gid));
  for (const witness of candidate.witnesses) {
    assert.equal(witness.edges.length, witness.path.length - 1);
    for (const [index, edge] of witness.edges.entries()) {
      assert.equal(edge.src, witness.path[index]);
      assert.equal(edge.dst, witness.path[index + 1]);
      assert.ok(observedEdges.has(`${edge.src}:${edge.dst}`));
      assert.ok(sentEdges.has(`${edge.src}:${edge.dst}`));
    }
  }
});
