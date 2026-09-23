import test from 'node:test';
import assert from 'node:assert/strict';
import { askAssistant, assistantStatus } from '../src/openai-assistant.mjs';

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

const gid = '100000000000000003';
const answer = { text: `У ${gid} наблюдаются признаки консолидации. Это гипотеза для проверки.`, references: [{ gid, reason: 'Общая точка двух потоков' }] };
const completed = (value = answer) => ({ status: 'completed', output: [{ type: 'message', content: [{ type: 'output_text', text: JSON.stringify(value) }] }] });

test('Responses API uses requested model, server key and grounded structured output', async () => {
  let sent;
  const result = await askAssistant({ question: 'Объясни роль', selectedId: gid }, data, {
    apiKey: 'test-secret-not-real',
    fetchImpl: async (url, options) => {
      sent = JSON.parse(options.body);
      assert.equal(url, 'https://api.openai.com/v1/responses');
      assert.equal(options.headers.Authorization, 'Bearer test-secret-not-real');
      assert.ok(options.signal);
      return Response.json(completed());
    },
  });
  assert.equal(sent.model, 'gpt-6-sol');
  assert.equal(sent.store, false);
  assert.equal(sent.text.format.type, 'json_schema');
  assert.equal(sent.text.format.strict, true);
  assert.equal(sent.tools, undefined);
  assert.match(sent.input, /100000000000000003/);
  assert.doesNotMatch(sent.input, /test-secret-not-real/);
  assert.equal(result.text, answer.text);
  assert.deepEqual(result.references, answer.references);
  assert.equal(result.model, 'gpt-6-sol');
  assert.doesNotMatch(JSON.stringify(result), /test-secret-not-real/);
});

test('missing key and invalid input cannot issue a paid request', async () => {
  const options = { apiKey: '', fetchImpl: () => assert.fail('unexpected API request') };
  assert.deepEqual(assistantStatus(''), { configured: false, model: 'gpt-6-sol' });
  await assert.rejects(askAssistant({ question: 'Объясни' }, data, options), { status: 503 });
  for (const payload of [null, {}, { question: ' ' }, { question: 'x'.repeat(4001) }, { question: 'Объясни', selectedId: 123 }]) {
    await assert.rejects(askAssistant(payload, data, { ...options, apiKey: 'test-key' }), { status: 400 });
  }
});

test('untrusted API errors never expose upstream body or key', async () => {
  for (const status of [401, 403, 404, 429, 500]) {
    await assert.rejects(askAssistant({ question: 'Объясни', selectedId: gid }, data, {
      apiKey: 'test-secret', fetchImpl: async () => Response.json({ error: { message: 'test-secret upstream detail' } }, { status }),
    }), error => {
      assert.doesNotMatch(error.message, /test-secret|upstream detail/);
      assert.ok([429, 502, 503].includes(error.status));
      return true;
    });
  }
});

test('unknown GID citations, malformed and incomplete responses are rejected', async () => {
  const bad = [
    completed({ text: 'Ответ', references: [{ gid: '199999999999999999', reason: 'выдумка' }] }),
    completed({ text: 'Узел 199999999999999999', references: [] }),
    completed({ text: `Узел ${gid}`, references: [] }),
    completed({ text: 'Ответ', references: [{ gid: Number(gid), reason: 'округление' }] }),
    completed({ text: '', references: [] }),
    completed({ text: 'Ответ', references: 'не массив' }),
    { status: 'incomplete', output: [] },
    { status: 'completed', output: [{ type: 'message', content: [{ type: 'refusal', refusal: 'no' }] }] },
    { status: 'completed', output: [{ type: 'message', content: [{ type: 'output_text', text: 'not json' }] }] },
  ];
  for (const response of bad) {
    await assert.rejects(askAssistant({ question: 'Объясни', selectedId: gid }, data, {
      apiKey: 'test-key', fetchImpl: async () => Response.json(response),
    }), { status: 502 });
  }
});

test('network failure and timeout have actionable controlled messages', async () => {
  for (const name of ['TypeError', 'TimeoutError', 'AbortError']) {
    await assert.rejects(askAssistant({ question: 'Объясни', selectedId: gid }, data, {
      apiKey: 'test-key', fetchImpl: async () => { const error = new Error('secret detail'); error.name = name; throw error; },
    }), error => error.status === (name === 'TypeError' ? 502 : 504) && !error.message.includes('secret detail'));
  }
});
