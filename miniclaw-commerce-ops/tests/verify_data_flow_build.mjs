import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const platformIndex = process.argv.indexOf('--platform-root');
const platformRoot = platformIndex >= 0 ? process.argv[platformIndex + 1] : process.env.MINICLAW_PLATFORM_ROOT;
assert.ok(platformRoot, 'Pass --platform-root with the pinned MiniClaw source and installed web dependencies.');
const temporaryRoot = path.join(projectRoot, 'tmp');
await mkdir(temporaryRoot, { recursive: true });
const fixtureRoot = await mkdtemp(path.join(temporaryRoot, 'portable-web-'));
assert.equal(path.dirname(fixtureRoot), temporaryRoot);

try {
  await mkdir(path.join(fixtureRoot, 'scripts'));
  await cp(path.join(projectRoot, 'native_app'), path.join(fixtureRoot, 'native_app'), { recursive: true });
  const buildScript = path.join(fixtureRoot, 'scripts', 'build-data-flow-web.mjs');
  await cp(path.join(projectRoot, 'scripts', 'build-data-flow-web.mjs'), buildScript);
  const result = spawnSync(process.execPath, [buildScript, '--platform-root', path.resolve(platformRoot)], {
    cwd: fixtureRoot,
    encoding: 'utf8',
    maxBuffer: 4 * 1024 * 1024,
    timeout: 180000,
  });
  assert.equal(result.status, 0, `Fresh checkout build failed: ${result.error?.message ?? result.stderr}`);
  const distRoot = path.join(fixtureRoot, 'runtime', 'web', 'dist');
  assert.match(await readFile(path.join(distRoot, 'index.html'), 'utf8'), /Data Flow/);
  const assetRoot = path.join(distRoot, 'assets');
  const cssFiles = (await readdir(assetRoot)).filter((name) => name.endsWith('.css'));
  const css = (await Promise.all(cssFiles.map((name) => readFile(path.join(assetRoot, name), 'utf8')))).join('\n');
  for (const selector of ['.max-w-lg', '.h-10', '.fixed']) {
    assert.ok(css.includes(selector), `Native component CSS missing in relocated checkout: ${selector}`);
  }
  process.stdout.write('Portable Data Flow build passed: fresh runtime output and native component CSS verified.\n');
} finally {
  await rm(fixtureRoot, { recursive: true, force: true });
}
