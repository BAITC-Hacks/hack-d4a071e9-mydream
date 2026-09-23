import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const reports = join(root, 'reports');
const temporary = join(reports, 'tmp');
mkdirSync(temporary, { recursive: true });
const python = process.env.PYTHON_BIN || join(root, 'track02', '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const suites = [
  { name: 'javascript', command: process.execPath, args: ['--test'], timeout: 120000 },
  { name: 'python', command: python,
    args: ['-m', 'unittest', 'discover', '-s', 'tests', '-p', '*_test.py', '-v'], timeout: 660000 },
];
const results = [];
for (const suite of suites) {
  process.stdout.write(`Running ${suite.name} checks...\n`);
  const started = performance.now();
  const result = spawnSync(suite.command, suite.args, {
    cwd: root, encoding: 'utf8', timeout: suite.timeout, windowsHide: true,
    maxBuffer: 4 * 1024 * 1024,
    env: { ...process.env, TEMP: temporary, TMP: temporary, TMPDIR: temporary,
      PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1',
      OPENAI_API_KEY: '', OPENAI_BASE_URL: '' },
  });
  const log = [result.stdout || '', result.stderr || '', result.error?.message || ''].join('\n');
  writeFileSync(join(reports, `${suite.name}-tests.txt`), log, 'utf8');
  process.stdout.write(log);
  results.push({ suite: suite.name, passed: result.status === 0 && !result.error,
    exit_code: result.status, elapsed_seconds: Number(((performance.now() - started) / 1000).toFixed(3)),
    log: `reports/${suite.name}-tests.txt` });
}
const passed = results.every(result => result.passed);
writeFileSync(join(reports, 'compliance-results.json'), JSON.stringify({
  checked_at: new Date().toISOString(), automated_checks_passed: passed,
  scope: 'Local contract and behavior tests; no paid model calls. Manual review: docs/SPEC_COMPLIANCE.md.',
  results,
}, null, 2) + '\n');
process.stdout.write(`\nAutomated checks: ${passed ? 'PASS' : 'FAIL'}. See reports/compliance-results.json\n`);
process.exitCode = passed ? 0 : 1;
