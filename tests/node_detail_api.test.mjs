import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { join } from 'node:path';

const projectRoot = process.cwd();
const selectedGid = '100000003115284100';
const senderGid = '100000003115284099';
const receiverGid = '100000003115284101';

async function freePort() {
  const listener = createServer();
  listener.listen(0, '127.0.0.1');
  await once(listener, 'listening');
  const port = listener.address().port;
  listener.close();
  await once(listener, 'close');
  return port;
}

async function startFixtureServer(context) {
  const fixtureBase = join(projectRoot, 'track02', 'fixtures', 'check');
  await mkdir(fixtureBase, { recursive: true });
  const fixtureRoot = await mkdtemp(join(fixtureBase, 'node-detail-'));
  const output = join(fixtureRoot, 'track02', 'out');
  await mkdir(output, { recursive: true });
  const selectedNode = {
    gid: selectedGid, role: 'consolidator', role_score: 0.96,
    cluster_id: 6, priority_score: 0.950669, evidence: 'Правило: 3 входа или больше',
    in_deg: 1, out_deg: 1, in_kzt: 23000, out_kzt: 8000,
    in_tx: 2, out_tx: 1, pagerank: 0.01, betweenness: 0.001,
    pass_through: 8000 / 23000, depth: 1, is_seed: false,
    truncated_by_depth: false, active_days: 3, data_quality: 1,
  };
  const incoming = { src: senderGid, dst: selectedGid, sum_kzt: 23000, n_tx: 2, depth: 1 };
  const outgoing = { src: selectedGid, dst: receiverGid, sum_kzt: 8000, n_tx: 1, depth: 2 };
  const cluster = {
    cluster_id: 6, n_nodes: 3, n_seed: 1, sum_kzt_internal: 31000,
    top_gids: selectedGid, hypothesis: 'Сходящиеся входящие переводы',
  };
  const transactions = [
    { src: senderGid, dst: selectedGid, date: '2026-07-05', sum_kzt: 11000,
      direction: 'incoming', counterparty: senderGid },
    { src: senderGid, dst: selectedGid, date: '2026-07-06', sum_kzt: 12000,
      direction: 'incoming', counterparty: senderGid },
    { src: selectedGid, dst: receiverGid, date: '2026-07-07', sum_kzt: 8000,
      direction: 'outgoing', counterparty: receiverGid },
  ];
  const network = {
    nodes: [selectedNode, { gid: senderGid }, { gid: receiverGid }],
    edges: [incoming, outgoing], clusters: [cluster], top: [], meta: {},
  };
  await writeFile(join(output, 'network.json'), JSON.stringify(network));
  await writeFile(join(output, 'transactions_by_gid.json'), JSON.stringify({
    [selectedGid]: transactions, [senderGid]: transactions.slice(0, 2),
    [receiverGid]: transactions.slice(2),
  }));

  const port = await freePort();
  const url = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, [join(projectRoot, 'server.mjs')], {
    cwd: fixtureRoot, env: { ...process.env, PORT: String(port) }, windowsHide: true,
    stdio: 'ignore',
  });
  context.after(async () => {
    if (child.exitCode === null) {
      child.kill();
      await once(child, 'close');
    }
    await rm(fixtureRoot, { recursive: true, force: true });
  });
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`Сервер завершился с кодом ${child.exitCode}`);
    try {
      const response = await fetch(`${url}/api/health`);
      if (response.ok) return { url, selectedNode, incoming, outgoing, cluster, transactions };
    } catch { /* Startup in progress. */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Сервер не открыл локальный порт за 4 секунды');
}

test('карточка GID возвращает полную гипотезу, все связи и исходные операции без округления GID', async (context) => {
  const fixture = await startFixtureServer(context);
  const response = await fetch(`${fixture.url}/api/node/${selectedGid}`);
  assert.equal(response.status, 200);
  const detail = await response.json();
  assert.deepEqual(detail, {
    gid: selectedGid, node: fixture.selectedNode,
    incoming: [fixture.incoming], outgoing: [fixture.outgoing],
    cluster: fixture.cluster, transactions: fixture.transactions,
  });
});

test('карточка GID отклоняет некорректный идентификатор и отличает неизвестный GID', async (context) => {
  const { url } = await startFixtureServer(context);
  const malformed = await fetch(`${url}/api/node/100000003115284100x`);
  assert.equal(malformed.status, 400);
  const unknown = await fetch(`${url}/api/node/100000003115284102`);
  assert.equal(unknown.status, 404);
});
