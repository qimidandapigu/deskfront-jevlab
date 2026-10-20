import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, cp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';

test('compiled SDK and example run outside checkout without game sources or node_modules', async () => {
  const root = fileURLToPath(new URL('..', import.meta.url));
  const isolated = await mkdtemp(join(tmpdir(), 'quickplay-sdk-isolated-'));
  try {
    for (const item of ['dist', 'examples', 'package.json']) await cp(join(root, item), join(isolated, item), { recursive: true });
    const { stdout } = await promisify(execFile)(process.execPath, ['examples/local-demo.mjs'], { cwd: isolated, timeout: 10000, windowsHide: true });
    const result = JSON.parse(stdout);
    assert.equal(result.environment, 'protocol-reference-only');
    assert.equal(result.submitted, 'queued'); assert.equal(result.actual, 'completed');
    assert.deepEqual(result.position, [.5, 0, 0]); assert.equal(result.controllerAfterRelease, 'native');
  } finally { await rm(isolated, { recursive: true, force: true }); }
});
