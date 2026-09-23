import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { askAssistant, assistantStatus, AssistantError, validateAssistantInput } from './src/openai-assistant.mjs';
import { createGraphAnalysisService, validateAnalysisInput } from './src/graph-analysis.mjs';

const root = process.cwd();
const port = Number(process.env.PORT || 4173);
const outDir = join(root, 'track02', 'out');
const networkPath = join(outDir, 'network.json');
const transactionsPath = join(outDir, 'transactions_by_gid.json');
const dataDir = join(root, 'track02', 'data');
const staticFiles = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/src/app.js', ['src/app.js', 'text/javascript; charset=utf-8']],
  ['/src/graph-layout.mjs', ['src/graph-layout.mjs', 'text/javascript; charset=utf-8']],
  ['/src/analysis-controller.mjs', ['src/analysis-controller.mjs', 'text/javascript; charset=utf-8']],
]);
const exportNames = new Set(['nodes_roles.csv', 'clusters.csv', 'top_nodes.csv']);
let rebuildPromise = null;
let assistantBusy = false;
const graphAnalysis = createGraphAnalysisService({ ask: runAssistant });

function assertLocalRequest(request) {
  const host = request.headers.host;
  const port = request.socket.localPort;
  const localHost = host === `127.0.0.1:${port}` || host === `localhost:${port}`;
  const origin = request.headers.origin;
  if (!localHost || (origin !== undefined && origin !== `http://${host}`)
    || request.headers['sec-fetch-site'] === 'cross-site') {
    request.resume();
    throw new AssistantError(403, 'Доступ разрешён только из локального интерфейса.');
  }
}

async function readAssistantRequest(request, validate = validateAssistantInput) {
  if (request.headers['content-type']?.split(';')[0].trim() !== 'application/json') throw new AssistantError(415, 'Требуется Content-Type: application/json.');
  if (Number(request.headers['content-length']) > 20000) { request.resume(); throw new AssistantError(413, 'Слишком большой запрос.'); }
  const chunks = [];
  let bytes = 0;
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > 20000) throw new AssistantError(413, 'Слишком большой запрос.');
    chunks.push(chunk);
  }
  let payload;
  try { payload = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { throw new AssistantError(400, 'Некорректный JSON запроса.'); }
  return validate(payload);
}

async function runAssistant(payload, network) {
  if (assistantBusy) throw new AssistantError(429, 'Дождитесь завершения текущего запроса к модели.');
  if (!assistantStatus().configured) throw new AssistantError(503, 'Задайте OPENAI_API_KEY в окружении сервера и перезапустите node server.mjs.');
  assistantBusy = true;
  try { return await askAssistant(payload, network); }
  finally { assistantBusy = false; }
}

function sendJson(response, status, value) {
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
  response.end(JSON.stringify(value));
}

async function fileExists(path) {
  try { return (await stat(path)).isFile(); }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

function pythonExecutable() {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  return process.platform === 'win32'
    ? join(root, 'track02', '.venv', 'Scripts', 'python.exe')
    : join(root, 'track02', '.venv', 'bin', 'python');
}

function runPipeline() {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonExecutable(), [
      join(root, 'track02', 'pipeline.py'),
      '--data', dataDir,
      '--out', outDir,
    ], { cwd: root, windowsHide: true });
    let output = '';
    const append = (chunk) => { output = (output + chunk.toString('utf8')).slice(-50000); };
    child.stdout.on('data', append);
    child.stderr.on('data', append);
    const timeout = setTimeout(() => child.kill(), 5 * 60 * 1000);
    child.on('error', (error) => { clearTimeout(timeout); reject(new Error(`Не удалось запустить Python: ${error.message}`)); });
    child.on('close', (code, signal) => {
      clearTimeout(timeout);
      if (code === 0) resolve(output);
      else reject(new Error(signal ? `Расчёт остановлен (${signal}).` : `Расчёт завершился с кодом ${code}: ${output.slice(-3000)}`));
    });
  });
}

createServer(async (request, response) => {
  try {
    assertLocalRequest(request);
    const pathname = new URL(request.url, `http://${request.headers.host}`).pathname;
    if (request.method === 'GET' && pathname === '/api/assistant/status') return sendJson(response, 200, assistantStatus());
    if (request.method === 'POST' && pathname === '/api/assistant') {
      const payload = await readAssistantRequest(request);
      if (!await fileExists(networkPath)) throw new AssistantError(409, 'Сначала пересчитайте модель графа.');
      const network = JSON.parse(await readFile(networkPath, 'utf8'));
      return sendJson(response, 200, await runAssistant(payload, network));
    }
    if (request.method === 'POST' && pathname === '/api/analysis') {
      const payload = await readAssistantRequest(request, validateAnalysisInput);
      if (!await fileExists(networkPath)) throw new AssistantError(409, 'Сначала пересчитайте модель графа.');
      const content = await readFile(networkPath, 'utf8');
      const version = createHash('sha256').update(content).digest('hex');
      return sendJson(response, 200, await graphAnalysis.analyze(payload, JSON.parse(content), version));
    }
    if (request.method === 'GET' && staticFiles.has(pathname)) {
      const [name, type] = staticFiles.get(pathname);
      const content = await readFile(join(root, name));
      response.writeHead(200, { 'content-type': type, 'cache-control': 'no-store' });
      return response.end(content);
    }
    if (request.method === 'GET' && pathname === '/api/health') {
      const inputNames = ['nodes.parquet', 'edges.parquet', 'transactions.parquet'];
      const dataReady = (await Promise.all(inputNames.map((name) => fileExists(join(dataDir, name))))).every(Boolean);
      const outputReady = await fileExists(networkPath) && await fileExists(transactionsPath);
      return sendJson(response, 200, { track: '02', dataReady, outputReady, rebuilding: Boolean(rebuildPromise) });
    }
    if (request.method === 'GET' && pathname === '/api/network') {
      if (!await fileExists(networkPath)) return sendJson(response, 404, { error: 'Расчёт ещё не выполнен. Нажмите «Пересчитать модель».' });
      const network = JSON.parse(await readFile(networkPath, 'utf8'));
      return sendJson(response, 200, network);
    }
    if (request.method === 'GET' && pathname.startsWith('/api/node/')) {
      const gid = pathname.slice('/api/node/'.length);
      if (!/^\d+$/.test(gid)) return sendJson(response, 400, { error: 'Некорректный GID.' });
      if (!await fileExists(networkPath)) return sendJson(response, 404, { error: 'Расчёт ещё не выполнен.' });
      const network = JSON.parse(await readFile(networkPath, 'utf8'));
      const node = network.nodes.find((item) => item.gid === gid);
      if (!node) return sendJson(response, 404, { error: 'GID не найден в наблюдаемом графе.' });
      if (!await fileExists(transactionsPath)) {
        return sendJson(response, 503, { error: 'Для просмотра исходных операций пересчитайте модель.' });
      }
      const transactionsByGid = JSON.parse(await readFile(transactionsPath, 'utf8'));
      return sendJson(response, 200, {
        gid,
        node,
        incoming: network.edges.filter((edge) => edge.dst === gid),
        outgoing: network.edges.filter((edge) => edge.src === gid),
        cluster: network.clusters.find((item) => item.cluster_id === node.cluster_id) ?? null,
        transactions: transactionsByGid[gid] ?? [],
      });
    }
    if (request.method === 'GET' && pathname.startsWith('/api/export/')) {
      const name = pathname.slice('/api/export/'.length);
      if (!exportNames.has(name)) return sendJson(response, 404, { error: 'Выгрузка не найдена.' });
      const content = await readFile(join(outDir, name));
      response.writeHead(200, {
        'content-type': 'text/csv; charset=utf-8',
        'content-disposition': `attachment; filename="${name}"`,
        'cache-control': 'no-store',
      });
      return response.end(content);
    }
    if (request.method === 'POST' && pathname === '/api/rebuild') {
      if (!rebuildPromise) rebuildPromise = runPipeline().finally(() => { rebuildPromise = null; });
      await rebuildPromise;
      return sendJson(response, 200, JSON.parse(await readFile(networkPath, 'utf8')));
    }
    sendJson(response, 404, { error: 'Маршрут не найден.' });
  } catch (error) {
    sendJson(response, error instanceof AssistantError ? error.status : error.code === 'ENOENT' ? 404 : 500, { error: error.message || 'Ошибка сервера.' });
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`Money Graph: http://127.0.0.1:${port}`);
});
