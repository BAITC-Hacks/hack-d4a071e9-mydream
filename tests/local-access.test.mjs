import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { access, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { request } from 'node:http';
import { createServer } from 'node:net';
import { join } from 'node:path';

const projectRoot = process.cwd();

async function freePort() {
  const listener = createServer();
  listener.listen(0, '127.0.0.1');
  await once(listener, 'listening');
  const port = listener.address().port;
  listener.close();
  await once(listener, 'close');
  return port;
}

function send(port, path, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const outgoing = request({ hostname: '127.0.0.1', port, path, method, headers }, (response) => {
      let text = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { text += chunk; });
      response.on('end', () => resolve({ status: response.statusCode, text }));
    });
    outgoing.on('error', reject);
    outgoing.end(body);
  });
}

async function startFixture(context) {
  const fixtureBase = join(projectRoot, 'track02', 'fixtures', 'check');
  await mkdir(fixtureBase, { recursive: true });
  const fixtureRoot = await mkdtemp(join(fixtureBase, 'local-access-'));
  assert.ok(fixtureRoot.startsWith(fixtureBase + '\\') || fixtureRoot.startsWith(fixtureBase + '/'));
  const output = join(fixtureRoot, 'track02', 'out');
  await mkdir(output, { recursive: true });
  const marker = join(fixtureRoot, 'pipeline-started');
  await writeFile(join(fixtureRoot, 'package.json'), '{"type":"commonjs"}');
  await writeFile(join(fixtureRoot, 'index.html'), '<!doctype html><title>Local graph fixture</title>');
  await writeFile(join(output, 'network.json'), JSON.stringify({
    nodes: [{ gid: '1', cluster_id: 1 }], edges: [], clusters: [], top: [], meta: {},
  }));
  await writeFile(join(output, 'transactions_by_gid.json'), '{"1":[]}');
  await writeFile(join(output, 'nodes_roles.csv'), 'gid,role\n1,peripheral\n');
  // A rebuild uses a real child process, but writes only a marker in this isolated fixture.
  await writeFile(join(fixtureRoot, 'track02', 'pipeline.py'),
    "require('node:fs').writeFileSync('pipeline-started', 'started');\n");

  const port = await freePort();
  const child = spawn(process.execPath, [join(projectRoot, 'server.mjs')], {
    cwd: fixtureRoot,
    env: { ...process.env, PORT: String(port), OPENAI_API_KEY: '', PYTHON_BIN: process.execPath },
    windowsHide: true,
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
    if (child.exitCode !== null) throw new Error(`Server exited with code ${child.exitCode}`);
    try {
      if ((await send(port, '/api/health')).status === 200) return { port, marker };
    } catch { /* Startup in progress. */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Local server did not start within four seconds');
}

test('foreign Host cannot read local graph, node, exports or static files', async (context) => {
  const { port } = await startFixture(context);
  for (const path of ['/api/network', '/api/node/1', '/api/export/nodes_roles.csv', '/']) {
    const response = await send(port, path, { headers: { Host: `foreign.example:${port}` } });
    assert.equal(response.status, 403, path);
    assert.ok(JSON.parse(response.text).error);
  }
  for (const host of ['127.0.0.1', `localhost:${port + 1}`, `localhost.evil.example:${port}`]) {
    assert.equal((await send(port, '/api/network', { headers: { Host: host } })).status, 403, host);
  }
});

test('foreign Origin rebuild is rejected before starting the pipeline', async (context) => {
  const { port, marker } = await startFixture(context);
  const response = await send(port, '/api/rebuild', {
    method: 'POST', headers: { Origin: 'https://foreign.example' },
  });
  await assert.rejects(access(marker), { code: 'ENOENT' }, 'Rejected requests must not start the pipeline');
  assert.equal(response.status, 403, response.text);
});

test('wrong Origin and cross-site fetches cannot read local data', async (context) => {
  const { port } = await startFixture(context);
  for (const headers of [
    { Origin: 'https://foreign.example' },
    { Origin: 'null' },
    { Origin: '' },
    { Origin: `http://127.0.0.1:${port + 1}` },
    { Origin: `http://localhost:${port}` },
    { 'Sec-Fetch-Site': 'cross-site' },
    { Origin: `http://127.0.0.1:${port}`, 'Sec-Fetch-Site': 'cross-site' },
  ]) {
    const response = await send(port, '/api/network', { headers });
    assert.equal(response.status, 403, JSON.stringify(headers));
  }
});

test('local UI and CLI requests remain available and assistant without a key returns 503', async (context) => {
  const { port } = await startFixture(context);
  for (const host of [`127.0.0.1:${port}`, `localhost:${port}`]) {
    for (const headers of [{ Host: host }, { Host: host, Origin: `http://${host}`, 'Sec-Fetch-Site': 'same-origin' }]) {
      assert.equal((await send(port, '/', { headers })).status, 200);
      const network = await send(port, '/api/network', { headers });
      assert.equal(network.status, 200);
      assert.equal(JSON.parse(network.text).nodes[0].gid, '1');
      const assistant = await send(port, '/api/assistant', {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: 'Объясни роль' }),
      });
      assert.equal(assistant.status, 503);
      assert.match(JSON.parse(assistant.text).error, /OPENAI_API_KEY/);
    }
  }
});
