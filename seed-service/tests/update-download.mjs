import test from 'node:test';
import assert from 'node:assert/strict';
import handler from '../netlify/functions/update-download.mjs';

const digest = 'a'.repeat(64);
const url = `https://test/.netlify/functions/update-download?tag=v9.8.7&id=123&size=100&sha256=${digest}`;

test('only bounded WWBS stable release ranges are accepted', async () => {
  assert.equal((await handler(new Request(url))).status, 400);
  assert.equal((await handler(new Request(url, {method: 'POST'}))).status, 405);
  assert.equal((await handler(new Request(url, {headers: {Range: 'bytes=0-5000000'}}))).status, 416);
  assert.equal((await handler(new Request(url.replace('v9.8.7', 'https://other.test'), {headers: {Range: 'bytes=0-15'}}))).status, 400);
});

test('stream validates the bounded range and fixed official upstream', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push(url);
    if (url.startsWith('https://api.github.com/')) return Response.json({tag_name: 'v9.8.7', assets: [{
      name: 'wwbs-exe.zip', state: 'uploaded', id: 123, size: 100,
      digest: `sha256:${digest}`, browser_download_url: 'https://github.com/ybpan34-prog/WWBS/releases/download/v9.8.7/wwbs-exe.zip',
    }]});
    assert.equal(options.headers.Range, 'bytes=0-15');
    return new Response(new Uint8Array(16), {status: 206, headers: {'Content-Range': 'bytes 0-15/100'}});
  };
  try {
    const response = await handler(new Request(url, {headers: {Range: 'bytes=0-15'}}));
    assert.equal(response.status, 206);
    assert.equal((await response.arrayBuffer()).byteLength, 16);
    assert.equal(response.headers.get('Content-Range'), 'bytes 0-15/100');
    assert.equal((await handler(new Request(url.replace('size=100', 'size=5'), {headers: {Range: 'bytes=0-15'}}))).status, 416);
    assert.ok(requests.every(url => url.startsWith('https://github.com/') || url.startsWith('https://api.github.com/')));
  } finally { globalThis.fetch = original; }
});
