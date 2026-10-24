// Only the public WWBS installer can pass through this route.
const OWNER = 'ybpan34-prog/WWBS';
const HOSTS = new Set(['github.com', 'api.github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com']);
const headers = {'User-Agent': 'WWBS-update-relay', 'Accept-Encoding': 'identity'};

async function official(url, options = {}) {
  for (let hop = 0; hop < 5; hop++) {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || !HOSTS.has(parsed.hostname)) throw Error('Invalid upstream');
    const response = await fetch(url, {...options, redirect: 'manual', signal: AbortSignal.timeout(12000)});
    if (![301, 302, 303, 307, 308].includes(response.status)) return response;
    const location = response.headers.get('location');
    await response.body?.cancel();
    if (!location) throw Error('Missing redirect');
    url = new URL(location, url).href;
  }
  throw Error('Too many redirects');
}

export default async function handler(request) {
  if (request.method !== 'GET') return new Response('GET only', {status: 405});
  const query = new URL(request.url).searchParams;
  if (query.get('health') === '1') return Response.json({service: 'WWBS installer relay', ranges: true});
  const tag = query.get('tag') || '';
  const id = query.get('id') || '';
  const digest = query.get('sha256') || '';
  const size = Number(query.get('size'));
  const range = /^bytes=(\d+)-(\d+)$/.exec(request.headers.get('range') || '');
  if (!/^v\d+\.\d+\.\d+$/.test(tag) || !/^\d+$/.test(id) || !/^[a-f0-9]{64}$/i.test(digest) || !range)
    return new Response('Invalid installer request', {status: 400});
  const start = Number(range[1]), end = Number(range[2]);
  if (!Number.isSafeInteger(size) || size < 1 || size > 512*1024*1024 || end >= size || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end < start || end-start+1 > 4*1024*1024)
    return new Response('Range too large', {status: 416});
  try {
    // Identity and SHA256 come from GitHub in the desktop client. The relay
    // never supplies metadata or an executable outside this fixed repository.
    // Avoid a shared unauthenticated API quota bottleneck for every chunk.
    const upstream = `https://github.com/${OWNER}/releases/download/${tag}/wwbs-exe.zip?wwbs_relay=${id}`;
    const response = await official(upstream, {headers: {...headers, Range: `bytes=${start}-${end}`, Accept: 'application/octet-stream'}});
    if (response.status !== 206 || response.headers.get('content-range') !== `bytes ${start}-${end}/${size}`) {
      await response.body?.cancel();
      return new Response('Invalid upstream range', {status: 502});
    }
    return new Response(response.body, {status: 206, headers: {
      'Content-Type': 'application/octet-stream',
      'Content-Length': String(end-start+1),
      'Content-Range': `bytes ${start}-${end}/${size}`,
      'Accept-Ranges': 'bytes',
      'Cache-Control': 'no-store',
    }});
  } catch {
    return new Response('Installer route temporarily unavailable', {status: 502});
  }
}

export const config = {rateLimit: {windowLimit: 180, windowSize: 60, aggregateBy: ['ip', 'domain']}};
