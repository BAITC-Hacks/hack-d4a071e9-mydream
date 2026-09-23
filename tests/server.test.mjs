import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { join } from 'node:path';

const root = process.cwd();

async function freePort() {
  const server = createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address();
  server.close();
  await once(server, 'close');
  return port;
}

async function waitForServer(url, child) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`Сервер завершился с кодом ${child.exitCode}`);
    try {
      const response = await fetch(`${url}/api/health`);
      if (response.ok) return;
    } catch { /* startup in progress */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Сервер не открыл локальный порт за 4 секунды');
}

test('локальный сервер выдаёт приложение и статус исходных данных', async (context) => {
  const port = await freePort();
  const url = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, [join(root, 'server.mjs')], {
    cwd: root,
    env: { ...process.env, PORT: String(port) },
    windowsHide: true,
    stdio: 'ignore',
  });
  context.after(async () => {
    if (child.exitCode === null) {
      child.kill();
      await once(child, 'close');
    }
  });

  await waitForServer(url, child);
  const healthResponse = await fetch(`${url}/api/health`);
  const health = await healthResponse.json();
  assert.equal(healthResponse.status, 200);
  assert.equal(health.track, '02');
  assert.equal(health.dataReady, true);

  const page = await fetch(url);
  assert.equal(page.status, 200);
  assert.match(page.headers.get('content-type'), /text\/html/);
  assert.match(await page.text(), /Граф денег/);

  const layoutModule = await fetch(url + '/src/graph-layout.mjs');
  assert.equal(layoutModule.status, 200);
  assert.match(layoutModule.headers.get('content-type'), /javascript/);
  assert.match(await layoutModule.text(), /clusterGrid/);
  const unknown = await fetch(`${url}/api/export/unknown.csv`);
  assert.equal(unknown.status, 404);
});
