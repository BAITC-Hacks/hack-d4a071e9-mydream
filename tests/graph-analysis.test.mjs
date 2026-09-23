import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:net';
import { join } from 'node:path';
import { createGraphAnalysisService, validateAnalysisInput } from '../src/graph-analysis.mjs';
import { buildAssistantContext } from '../src/assistant-context.mjs';

const id = (n) => `100000000000000${String(n).padStart(3, '0')}`;
const network = {
  nodes: Array.from({ length: 12 }, (_, index) => ({ gid: id(index + 1), priority_score: index < 2 ? 1 : (12 - index) / 20, role: 'consolidator' })).reverse(),
  edges: [],
};
const expected = Array.from({ length: 10 }, (_, index) => id(index + 1));
const output = (gids) => ({ text: 'Объяснение рассчитанных признаков и план проверки.', references: gids.map(gid => ({ gid, reason: 'Факты из расчёта' })), model: 'gpt-6-sol', scope: {} });
const answer = (payload, data) => output(buildAssistantContext(payload.question, data, payload.selectedId).sources);

test('overview sends all top10 in stable priority order to the external assistant context', async () => {
  let supplied;
  const service = createGraphAnalysisService({ ask: async (payload, data) => { supplied = payload; return answer(payload, data); }, now: () => new Date('2026-09-23T07:00:00Z') });
  const result = await service.analyze({ mode: 'overview' }, network, 'dataset-a');
  assert.deepEqual(supplied.question.match(/\b\d{18}\b/g), expected);
  assert.deepEqual(buildAssistantContext(supplied.question, network).sources, expected);
  assert.deepEqual(result.focus_gids, expected);
  assert.equal(result.mode, 'overview');
  assert.equal(result.gid, null);
  assert.equal(result.model, 'gpt-6-sol');
  assert.equal(result.generated_at, '2026-09-23T07:00:00.000Z');
  assert.equal(result.cached, false);
});

test('node summary preserves exact GID and rejects unknown IDs before any paid call', async () => {
  const service = createGraphAnalysisService({ ask: answer });
  const result = await service.analyze({ mode: 'node', gid: id(12) }, network, 'dataset-a');
  assert.deepEqual(result.focus_gids, [id(12)]);
  assert.equal(result.gid, id(12));
  const mustNotCall = createGraphAnalysisService({ ask: () => assert.fail('unknown GID issued a paid request') });
  await assert.rejects(mustNotCall.analyze({ mode: 'node', gid: id(99) }, network, 'dataset-a'), { status: 404 });
  for (const payload of [null, {}, { mode: 'invalid' }, { mode: 'node', gid: Number(id(12)) }, { mode: 'node', gid: '12' }, { mode: 'overview', gid: id(1) }]) {
    assert.throws(() => validateAnalysisInput(payload), { status: 400 });
  }
});

test('same content reuses response and changing dataset version invalidates summaries', async () => {
  let generation = 0;
  const service = createGraphAnalysisService({ ask: (payload, data) => ({ ...answer(payload, data), text: `Ответ ${++generation}` }) });
  const first = await service.analyze({ mode: 'overview' }, network, 'a');
  const cached = await service.analyze({ mode: 'overview' }, network, 'a');
  assert.equal(cached.text, first.text);
  assert.equal(cached.generated_at, first.generated_at);
  assert.equal(cached.cached, true);
  const changed = await service.analyze({ mode: 'overview' }, network, 'b');
  assert.equal(changed.text, 'Ответ 2');
  assert.equal(changed.cached, false);
});

test('identical concurrent requests share one answer and old inflight results cannot repopulate new cache', async () => {
  let resolveOld;
  let generation = 0;
  const service = createGraphAnalysisService({ ask: (payload, data) => {
    generation += 1;
    if (generation === 1) return new Promise(resolve => { resolveOld = () => resolve({ ...answer(payload, data), text: 'Старый граф' }); });
    return { ...answer(payload, data), text: 'Новый граф' };
  } });
  const one = service.analyze({ mode: 'overview' }, network, 'a');
  const duplicate = service.analyze({ mode: 'overview' }, network, 'a');
  const changed = await service.analyze({ mode: 'overview' }, network, 'b');
  resolveOld();
  assert.equal((await one).text, 'Старый граф');
  assert.equal((await duplicate).cached, true);
  assert.equal(changed.text, 'Новый граф');
  assert.equal((await service.analyze({ mode: 'overview' }, network, 'b')).cached, true);
  assert.equal(generation, 2);
});

test('errors and missing focus references are not cached', async () => {
  let generation = 0;
  const service = createGraphAnalysisService({ ask: (payload, data) => {
    generation += 1;
    if (generation === 1) throw new Error('API unavailable');
    if (generation === 2) return output([id(1)]);
    return answer(payload, data);
  } });
  await assert.rejects(service.analyze({ mode: 'overview' }, network, 'a'), /API unavailable/);
  await assert.rejects(service.analyze({ mode: 'overview' }, network, 'a'), { status: 502 });
  const complete = await service.analyze({ mode: 'overview' }, network, 'a');
  assert.equal(complete.cached, false);
  assert.equal(complete.references.length, 10);
  assert.equal((await service.analyze({ mode: 'overview' }, network, 'a')).cached, true);
});

test('cache has a bounded least recently used capacity', async () => {
  let generation = 0;
  const service = createGraphAnalysisService({ maxEntries: 2, ask: (payload, data) => ({ ...answer(payload, data), text: `Ответ ${++generation}` }) });
  const first = await service.analyze({ mode: 'node', gid: id(1) }, network, 'a');
  await service.analyze({ mode: 'node', gid: id(2) }, network, 'a');
  assert.equal((await service.analyze({ mode: 'node', gid: id(1) }, network, 'a')).cached, true);
  await service.analyze({ mode: 'node', gid: id(3) }, network, 'a');
  assert.equal((await service.analyze({ mode: 'node', gid: id(1) }, network, 'a')).text, first.text);
  assert.equal((await service.analyze({ mode: 'node', gid: id(2) }, network, 'a')).cached, false);
});

test('analysis endpoint keeps local origin, JSON and key protections without making an API call', async (context) => {
  const listener = createServer();
  listener.listen(0, '127.0.0.1');
  await once(listener, 'listening');
  const port = listener.address().port;
  listener.close();
  await once(listener, 'close');
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, [join(process.cwd(), 'server.mjs')], {
    cwd: process.cwd(), env: { ...process.env, PORT: String(port), OPENAI_API_KEY: '' }, windowsHide: true, stdio: 'ignore',
  });
  context.after(async () => { if (child.exitCode === null) { child.kill(); await once(child, 'close'); } });
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`Server exited: ${child.exitCode}`);
    try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* Starting. */ }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const post = (body, headers = {}) => fetch(`${base}/api/analysis`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body,
  });
  const missingKey = await post(JSON.stringify({ mode: 'overview' }));
  assert.equal(missingKey.status, 503);
  assert.match((await missingKey.json()).error, /OPENAI_API_KEY/);
  assert.equal((await post(JSON.stringify({ mode: 'node', gid: '199999999999999999' }))).status, 404);
  assert.equal((await post('{broken')).status, 400);
  assert.equal((await post(JSON.stringify({ mode: 'unexpected' }))).status, 400);
  assert.equal((await post(JSON.stringify({ mode: 'overview', padding: 'x'.repeat(21000) }))).status, 413);
  assert.equal((await post('{}', { 'Content-Type': 'text/plain' })).status, 415);
  assert.equal((await post('{}', { Origin: 'https://untrusted.example' })).status, 403);
  assert.equal((await fetch(`${base}/src/graph-analysis.mjs`)).status, 404);
});
