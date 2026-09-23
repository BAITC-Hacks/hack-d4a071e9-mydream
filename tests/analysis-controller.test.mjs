import test from 'node:test';
import assert from 'node:assert/strict';
import { createAnalysisController } from '../src/analysis-controller.mjs';

function fakeClock() {
  let now = 0;
  let nextId = 1;
  const timers = new Map();
  return {
    setTimer(callback, delay) {
      const id = nextId++;
      timers.set(id, { callback, at: now + delay });
      return id;
    },
    clearTimer(id) { timers.delete(id); },
    advance(duration) {
      const target = now + duration;
      while (true) {
        const next = [...timers].filter(([, timer]) => timer.at <= target)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        const [id, timer] = next;
        timers.delete(id);
        now = timer.at;
        timer.callback();
      }
      now = target;
    },
  };
}

function harness(options = {}) {
  const clock = fakeClock();
  const calls = [];
  const changes = [];
  const busy = [];
  const controller = createAnalysisController({
    request(payload) {
      let resolve;
      let reject;
      const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
      calls.push({ payload, resolve, reject });
      return promise;
    },
    onChange(change) { changes.push(change); },
    onBusyChange(value) { busy.push(value); },
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    ...options,
  });
  const select = (key) => controller.select({ key, payload: { selection: key } });
  return { controller, clock, calls, changes, busy, select };
}

async function flush() {
  for (let turn = 0; turn < 5; turn += 1) await Promise.resolve();
}

test('rapid selections send only the latest payload after 600 ms of quiet', async () => {
  const h = harness();
  h.select('a');
  h.clock.advance(300);
  h.select('b');
  h.clock.advance(500);
  h.select('c');
  h.clock.advance(599);
  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.busy, []);
  assert.deepEqual(h.changes.at(-1), { status: 'waiting', key: 'c' });
  h.clock.advance(1);
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.calls[0].payload, { selection: 'c' });
  assert.deepEqual(h.changes.at(-1), { status: 'loading', key: 'c' });
  assert.deepEqual(h.busy, [true]);
  h.calls[0].resolve({ answer: 'C', cached: false });
  await flush();
  assert.deepEqual(h.changes.at(-1), { status: 'ready', key: 'c', data: { answer: 'C', cached: false } });
  assert.deepEqual(h.busy, [true, false]);
});

test('the same selection never restarts the timer or repeats an active or completed request', async () => {
  const h = harness();
  h.select('a');
  h.clock.advance(300);
  h.select('a');
  h.clock.advance(300);
  assert.equal(h.calls.length, 1);
  h.select('a');
  h.clock.advance(1000);
  assert.equal(h.calls.length, 1);
  h.calls[0].resolve({ answer: 'A' });
  await flush();
  h.select('a');
  h.clock.advance(1000);
  assert.equal(h.calls.length, 1);
});

test('returning to a cached selection immediately reuses the answer without marking it busy', async () => {
  const h = harness();
  for (const key of ['a', 'b']) {
    h.select(key);
    h.clock.advance(600);
    h.calls.at(-1).resolve({ answer: key.toUpperCase(), cached: false });
    await flush();
  }
  h.select('a');
  assert.deepEqual(h.changes.at(-1), { status: 'ready', key: 'a', data: { answer: 'A', cached: true } });
  h.clock.advance(600);
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.busy, [true, false, true, false]);
});

test('the cache evicts the least recently used result when its bound is reached', async () => {
  const h = harness({ maxEntries: 2 });
  for (const key of ['a', 'b']) {
    h.select(key);
    h.clock.advance(600);
    h.calls.at(-1).resolve({ answer: key });
    await flush();
  }
  h.select('a');
  h.select('c');
  h.clock.advance(600);
  h.calls.at(-1).resolve({ answer: 'c' });
  await flush();
  h.select('a');
  assert.equal(h.changes.at(-1).data.cached, true);
  h.select('b');
  assert.deepEqual(h.changes.at(-1), { status: 'waiting', key: 'b' });
  h.clock.advance(600);
  assert.deepEqual(h.calls.map(({ payload }) => payload.selection), ['a', 'b', 'c', 'b']);
});

test('an active request never overlaps another and its stale result never replaces the selection', async () => {
  const h = harness();
  h.select('a');
  h.clock.advance(600);
  h.select('b');
  h.clock.advance(600);
  assert.equal(h.calls.length, 1);
  h.select('c');
  h.clock.advance(100);
  h.calls[0].resolve({ answer: 'stale A' });
  await flush();
  assert.equal(h.calls.length, 1);
  assert.ok(!h.changes.some((change) => change.status === 'ready'));
  h.clock.advance(499);
  assert.equal(h.calls.length, 1);
  h.clock.advance(1);
  assert.deepEqual(h.calls.map(({ payload }) => payload.selection), ['a', 'c']);
  h.calls[1].resolve({ answer: 'C' });
  await flush();
  assert.deepEqual(h.changes.at(-1), { status: 'ready', key: 'c', data: { answer: 'C' } });
  assert.deepEqual(h.busy, [true, false, true, false]);
});

test('clear invalidates an old response even when the next graph uses the same key', async () => {
  const h = harness();
  h.select('a');
  h.clock.advance(600);
  h.controller.clear();
  h.select('a');
  h.clock.advance(600);
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.busy, [true]);
  h.calls[0].resolve({ answer: 'old graph' });
  await flush();
  assert.equal(h.calls.length, 2);
  assert.ok(!h.changes.some((change) => change.status === 'ready'));
  h.calls[1].resolve({ answer: 'new graph' });
  await flush();
  assert.equal(h.changes.at(-1).data.answer, 'new graph');
  h.controller.clear();
  h.select('a');
  h.clock.advance(600);
  assert.equal(h.calls.length, 3);
});

test('clear removes a pending selection and does not cache an invalidated response', async () => {
  const h = harness();
  h.select('a');
  h.controller.clear();
  h.clock.advance(600);
  assert.equal(h.calls.length, 0);
  h.select('a');
  h.clock.advance(600);
  h.controller.clear();
  const before = h.changes.length;
  h.calls[0].resolve({ answer: 'invalid' });
  await flush();
  assert.equal(h.changes.length, before);
  assert.deepEqual(h.busy, [true, false]);
  h.select('a');
  assert.deepEqual(h.changes.at(-1), { status: 'waiting', key: 'a' });
});

test('a failed selection waits for explicit retry and returns the original Error', async () => {
  const h = harness();
  h.select('a');
  h.clock.advance(600);
  const failure = new Error('upstream unavailable');
  h.calls[0].reject(failure);
  await flush();
  assert.deepEqual(h.changes.at(-1), { status: 'error', key: 'a', error: failure });
  h.select('a');
  h.clock.advance(6000);
  assert.equal(h.calls.length, 1);
  h.controller.retry();
  assert.equal(h.calls.length, 2);
  h.calls[1].resolve({ answer: 'retry succeeded' });
  await flush();
  assert.equal(h.changes.at(-1).data.answer, 'retry succeeded');
  h.controller.retry();
  h.clock.advance(6000);
  assert.equal(h.calls.length, 2);
});

test('a stale failure does not block the pending current selection or offer its retry', async () => {
  const h = harness();
  h.select('a');
  h.clock.advance(600);
  h.select('b');
  h.clock.advance(600);
  h.calls[0].reject(new Error('failure for A'));
  await flush();
  assert.deepEqual(h.calls.map(({ payload }) => payload.selection), ['a', 'b']);
  assert.ok(!h.changes.some((change) => change.status === 'error'));
  h.controller.retry();
  assert.equal(h.calls.length, 2);
  h.calls[1].resolve({ answer: 'B' });
  await flush();
  assert.equal(h.changes.at(-1).data.answer, 'B');
});

test('pausing holds the latest pending selection until resumed', async () => {
  const h = harness();
  h.controller.setPaused(true);
  h.select('a');
  h.clock.advance(600);
  h.select('b');
  h.clock.advance(600);
  assert.equal(h.calls.length, 0);
  assert.deepEqual(h.busy, []);
  h.controller.setPaused(false);
  assert.deepEqual(h.calls.map(({ payload }) => payload.selection), ['b']);
  h.controller.setPaused(true);
  h.select('c');
  h.clock.advance(600);
  h.calls[0].resolve({ answer: 'B' });
  await flush();
  assert.equal(h.calls.length, 1);
  h.controller.setPaused(false);
  assert.deepEqual(h.calls.map(({ payload }) => payload.selection), ['b', 'c']);
});

test('retry from an error callback preserves actual busy state and catches synchronous failures', async () => {
  const clock = fakeClock();
  const events = [];
  let attempts = 0;
  let controller;
  controller = createAnalysisController({
    request() {
      attempts += 1;
      events.push('request');
      if (attempts === 1) throw 'temporary failure';
      return Promise.resolve({ answer: 'recovered' });
    },
    onBusyChange(busy) { events.push(`busy:${busy}`); },
    onChange(change) {
      events.push(change.status);
      if (change.status === 'error') {
        assert.ok(change.error instanceof Error);
        controller.retry();
      }
    },
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
  });
  controller.select({ key: 'a', payload: {} });
  clock.advance(600);
  await flush();
  assert.equal(attempts, 2);
  assert.deepEqual(events, [
    'waiting', 'busy:true', 'loading', 'request', 'busy:false', 'error',
    'waiting', 'busy:true', 'loading', 'request', 'busy:false', 'ready',
  ]);
});
