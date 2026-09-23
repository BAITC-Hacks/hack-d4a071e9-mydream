import test from 'node:test';
import assert from 'node:assert/strict';
import { verificationPlan } from '../src/app.js';

test('план проверки показывает недостающие данные для любого выбранного узла', () => {
  const plan = verificationPlan({ gid: '123', depth: 2, is_seed: false, in_deg: 3, out_deg: 2 });
  assert.deepEqual(plan.map((item) => item.key), ['fullFlow', 'timing', 'operationType', 'validation']);
  assert.ok(plan.every((item) => item.required && item.purpose));
  assert.doesNotMatch(JSON.stringify(plan), /KYC|ФИО|ИИН|бенефициар|межбанковск/i);
});

test('план выделяет границы выборки для исходного клиента и четвёртого колена', () => {
  const seed = verificationPlan({ gid: '1', depth: 0, is_seed: true });
  const boundary = verificationPlan({ gid: '4', depth: 4, is_seed: false });
  assert.equal(seed[0].key, 'seedIncoming');
  assert.equal(boundary[0].key, 'depthFourOutgoing');
});
