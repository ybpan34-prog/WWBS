"""Probe official and project-operated routes; all bytes remain SHA256 checked."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import http.client
import threading
import time
import urllib.request
from urllib.parse import urlencode, urlsplit


RELAY = 'https://wwbs-seed-library.netlify.app/.netlify/functions/update-download'
ALLOWED = {'github.com', 'api.github.com', 'release-assets.githubusercontent.com',
           'objects.githubusercontent.com', 'wwbs-seed-library.netlify.app'}


def relay_url(asset, version):
    parts = urlsplit(str(asset.get('browser_download_url', '')))
    digest = str(asset.get('digest', ''))
    if (parts.hostname != 'github.com' or not parts.path.startswith('/ybpan34-prog/WWBS/releases/download/')
            or not digest.startswith('sha256:') or not asset.get('id')):
        return None
    tag = parts.path.split('/')[-2]
    return RELAY+'?'+urlencode({'tag': tag, 'id': asset['id'], 'sha256': digest.split(':')[1], 'size': asset.get('size', 0)})


class DownloadRoutes:
    def __init__(self, urls, headers, size, opener, cancelled, status):
        self.urls, self.headers, self.size = urls, headers, size
        self.opener, self.cancelled, self.status = opener, cancelled, status
        self.current = None
        self.lock = threading.Lock()

    def _probe(self, url):
        started = time.monotonic()
        end = min(self.size-1, 64*1024-1)
        request = urllib.request.Request(url, headers=dict(self.headers, Range=f'bytes=0-{end}'))
        with self.opener(request, timeout=4) as response:
            if (response.status != 206 or response.headers.get('Content-Range') != f'bytes 0-{end}/{self.size}'
                    or response.headers.get('Content-Encoding', 'identity') != 'identity'):
                raise OSError('下载线路不支持正确分段')
            resolved = response.geturl()
            parsed = urlsplit(resolved)
            if parsed.scheme != 'https' or parsed.hostname not in ALLOWED:
                raise ValueError('下载重定向地址不可信')
            read = getattr(response, 'read1', response.read)
            received = 0
            while received <= end and not self.cancelled():
                data = read(min(16*1024, end+1-received))
                if not data:
                    raise OSError('下载线路测速中断')
                received += len(data)
                if time.monotonic()-started > 3:
                    raise TimeoutError('下载线路测速过慢')
            if self.cancelled():
                raise InterruptedError('更新已取消')
        return resolved, time.monotonic()-started

    def select(self):
        self.status('正在比较直连与加速线路…')
        errors, choices = [], []
        with ThreadPoolExecutor(max_workers=len(self.urls), thread_name_prefix='wwbs-route') as pool:
            futures = [pool.submit(self._probe, url) for url in self.urls]
            for future in as_completed(futures):
                try:
                    choices.append(future.result())
                except (OSError, ValueError, http.client.HTTPException) as error:
                    errors.append(error)
        if self.cancelled():
            raise InterruptedError('更新已取消')
        if not choices:
            raise OSError('下载线路均不可用：'+str(errors[-1]))
        self.available = [url for url, _seconds in sorted(choices, key=lambda item: item[1])]
        self.current = self.available[0]
        self.status('使用项目加速线路下载' if urlsplit(self.current).hostname == 'wwbs-seed-library.netlify.app'
                    else '使用GitHub直连下载')
        return self.current

    def switch(self, failed):
        with self.lock:
            if self.current == failed:
                alternatives = [url for url in self.available if url != failed]
                if alternatives:
                    self.current = alternatives[0]
                    self.status('连接偏慢，切换下载线路并继续已下载分段…')
            return self.current
