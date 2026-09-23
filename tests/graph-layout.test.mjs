import test from 'node:test';
import assert from 'node:assert/strict';
import { clusterGrid, selectClusterNodes, layoutByDepth, selectEgoEdges } from '../src/graph-layout.mjs';

test('обзор кластеров размещает группы без наложения в узком canvas', () => {
  const clusters = Array.from({ length: 66 }, (_, i) => ({ cluster_id: i, n_nodes: 66 - i }));
  const points = clusterGrid(clusters, 400, 495);
  assert.equal(points.length, 66);
  for (let i = 0; i < points.length; i++) {
    for (let j = i + 1; j < points.length; j++) {
      assert.ok(Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y) >= points[i].radius + points[j].radius + 7);
    }
  }
});

test('кластер показывает ограниченное число узлов на каждом колене и сохраняет выбранный', () => {
  const nodes = Array.from({ length: 240 }, (_, i) => ({ gid: String(i), depth: i % 5, priority_score: (240 - i) / 240 }));
  const shown = selectClusterNodes(nodes, '239', 18);
  assert.ok(shown.length <= 90);
  assert.ok(shown.some((node) => node.gid === '239'));
  const points = layoutByDepth(shown, 700, 495);
  for (const depth of [0, 1, 2, 3, 4]) {
    const inLayer = points.filter((point) => point.node.depth === depth);
    for (let i = 1; i < inLayer.length; i++) assert.ok(inLayer[i].y - inLayer[i - 1].y >= 20);
  }
});

test('связи узла ограничены по сумме и остаются на своих сторонах', () => {
  const incoming = Array.from({ length: 90 }, (_, i) => ({ src: String(i), dst: 'center', sum_kzt: i }));
  const outgoing = Array.from({ length: 90 }, (_, i) => ({ src: 'center', dst: String(i), sum_kzt: i }));
  const selected = selectEgoEdges(incoming, outgoing, 400);
  assert.equal(selected.incoming.length, 24);
  assert.equal(selected.outgoing.length, 24);
  assert.equal(selected.incoming[0].sum_kzt, 89);
  assert.equal(selected.outgoing[0].sum_kzt, 89);
});