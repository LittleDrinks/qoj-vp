const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash} = require('node:crypto');

async function setup(t, change = {}) {
  const {recoverVersion} = await import('../scripts/recover_amo_version.mjs');
  const scratch = path.join(__dirname, '../.scratch');
  await fs.mkdir(scratch, {recursive: true});
  const outputDir = await fs.mkdtemp(path.join(scratch, 'amo-'));
  t.after(() => fs.rm(outputDir, {recursive: true}));
  const bytes = Buffer.from('signed-file-fixture'), calls = [];
  const record = {version: '0.3.3', channel: 'unlisted', file: {status: 'public',
    url: 'https://addons.mozilla.org/firefox/downloads/file/1/fixture.xpi',
    hash: 'sha256:' + createHash('sha256').update(bytes).digest('hex'), ...change.file}, ...change.record};
  const fetchImpl = async (url, options) => {
    calls.push({url, options});
    if (url.includes('/api/')) return new Response(JSON.stringify(record), {status: change.status || 200});
    if (change.redirect && calls.length === 2) return new Response(null, {status: 302, headers: {location: change.redirect}});
    return new Response(change.bytes || bytes);
  };
  return {calls, bytes, outputDir, run: () => recoverVersion({id: 'fixture@example', version: '0.3.3',
    outputDir, getAuthHeader: async () => 'JWT test-placeholder', fetchImpl})};
}
test('approved AMO version is fetched read-only and hash verified', async t => {
  const e = await setup(t), result = await e.run();
  assert.equal(result.downloaded, true);
  assert.deepEqual(await fs.readFile(result.path), e.bytes);
  assert.equal(e.calls.length, 2);
  assert.ok(e.calls.every(c => !c.options.method || c.options.method === 'GET'));
});
test('a missing version allows the normal signing path', async t => {
  const e = await setup(t, {status: 404});
  assert.deepEqual(await e.run(), {downloaded: false});
  assert.equal(e.calls.length, 1);
});
test('auth failures and pending reviews never cause a new upload', async t => {
  for (const change of [{status: 401}, {file: {status: 'unreviewed'}}, {record: {channel: 'listed'}}]) {
    const e = await setup(t, change);
    await assert.rejects(e.run());
    assert.equal(e.calls.length, 1);
    assert.deepEqual(await fs.readdir(e.outputDir), []);
  }
});
test('corrupt download cannot be released', async t => {
  const e = await setup(t, {bytes: Buffer.from('tampered')});
  await assert.rejects(e.run(), /file hash/);
  assert.deepEqual(await fs.readdir(e.outputDir), []);
});
test('foreign redirects are rejected before credentials can be forwarded', async t => {
  const e = await setup(t, {redirect: 'https://example.com/file.xpi'});
  await assert.rejects(e.run(), /download origin/);
  assert.equal(e.calls.length, 2);
});
test('Mozilla CDN receives no AMO Authorization header', async t => {
  const e = await setup(t, {redirect: 'https://addons.cdn.mozilla.net/file.xpi'});
  assert.equal((await e.run()).downloaded, true);
  assert.equal(e.calls[2].options.headers.Authorization, undefined);
});
