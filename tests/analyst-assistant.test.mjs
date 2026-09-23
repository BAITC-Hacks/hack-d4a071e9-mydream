import test from 'node:test';
import assert from 'node:assert/strict';
import { answerQuestion } from '../src/app.js';

const data = {
  nodes: [
    { gid: '100000000000000001', role: 'peripheral', priority_score: .2 },
    { gid: '100000000000000002', role: 'peripheral', priority_score: .2 },
    { gid: '100000000000000003', role: 'consolidator', priority_score: .8 },
    { gid: '100000000000000004', role: 'transit', priority_score: .5 },
  ],
  edges: [
    { src: '100000000000000001', dst: '100000000000000003', sum_kzt: 10000 },
    { src: '100000000000000002', dst: '100000000000000003', sum_kzt: 20000 },
    { src: '100000000000000003', dst: '100000000000000004', sum_kzt: 30000 },
  ],
  optional: { cycles: [], repeated_routes: [], resilience: { remove_top: [] } },
};

test('помощник находит общую точку сбора только по переданным GID', () => {
  const answer = answerQuestion('Кто собирает деньги с 100000000000000001 и 100000000000000002?', data);
  assert.equal(answer.references[0].gid, '100000000000000003');
  assert.match(answer.text, /2 исходных/);
  assert.match(answer.text, /гипотез/);
});

test('помощник не выдумывает ответ при отсутствии исходных GID', () => {
  const answer = answerQuestion('Кто собирает деньги?', data);
  assert.equal(answer.references.length, 0);
  assert.match(answer.text, /Укажите/);
});
