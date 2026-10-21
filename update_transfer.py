"""Verified, resumable range downloads using GitHub's own release CDN."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import http.client
import os
from pathlib import Path
import re
import shutil
import threading
import time
import urllib.request
from urllib.parse import urlsplit


class RangesUnavailable(RuntimeError):
    pass


@contextmanager
def cache_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'lock').open('a+b') as stream:
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _range(response, start, end, size):
    value = response.headers.get('Content-Range', '')
    if (response.status != 206 or value != f'bytes {start}-{end}/{size}'
            or response.headers.get('Content-Encoding', 'identity') != 'identity'):
        raise RangesUnavailable('服务器未正确响应分段范围')


def _verified(path, digest, size):
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() == digest


def _copy(source, destination):
    destination.unlink(missing_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


def download_ranges(asset, destination, *, version, progress, cancelled, opener,
                    cache_dir, status, sleep=time.sleep):
    """Return False only for a server without ranges; never accept unverified bytes."""
    size = int(asset.get('size') or 0)
    digest = str(asset.get('digest') or '')
    if size < 8*1024*1024 or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        return False
    checksum = digest.split(':')[1].lower()
    folder = Path(cache_dir)/checksum
    with cache_lock(folder):
        return _download(asset, destination, size, checksum, folder, version,
                         progress, cancelled, opener, status, sleep)


def _download(asset, destination, size, checksum, folder, version,
              progress, cancelled, opener, status, sleep):
    if cancelled():
        raise InterruptedError('更新已取消，下载断点已保留')
    complete = folder/'complete.zip'
    if _verified(complete, checksum, size):
        status('使用已校验的本地更新包')
        _copy(complete, destination)
        progress(size, size)
        return True
    headers = {'User-Agent':'wwbs/'+version, 'Accept':'application/octet-stream',
               'Accept-Encoding':'identity', 'Cache-Control':'no-cache'}
    # Resolve once. Every worker uses the same immutable signed asset URL, so a
    # release replaced during the transfer cannot silently mix multiple builds.
    status('正在连接官方下载服务器…')
    base = asset['browser_download_url']
    url = base+('&' if '?' in base else '?')+'wwbs_update='+str(time.time_ns())
    request = urllib.request.Request(url, headers=dict(headers, Range='bytes=0-0'))
    try:
        with opener(request, timeout=8) as response:
            _range(response, 0, 0, size)
            direct = response.geturl()
            parts = urlsplit(direct)
            if parts.scheme != 'https' or parts.hostname not in {
                    'github.com', 'api.github.com', 'release-assets.githubusercontent.com',
                    'objects.githubusercontent.com'}:
                raise ValueError('更新包重定向地址不是GitHub官方地址')
    except RangesUnavailable:
        return False
    boundaries = [(size*i//4, size*(i+1)//4-1) for i in range(4)]
    paths = [folder/f'part-{index}' for index in range(4)]
    counts = []
    for path, (start, end) in zip(paths, boundaries):
        length = path.stat().st_size if path.exists() else 0
        if length > end-start+1:
            path.unlink()
            length = 0
        counts.append(length)
    progress(sum(counts), size)
    status('正在续传安装包…' if any(counts) else '正在下载安装包…')
    lock, abort = threading.Lock(), threading.Event()
    errors = []

    def worker(index):
        start, end = boundaries[index]
        for attempt in range(3):
            if cancelled() or abort.is_set():
                return
            offset = counts[index]
            if offset == end-start+1:
                return
            request = urllib.request.Request(direct, headers=dict(headers, Range=f'bytes={start+offset}-{end}'))
            try:
                with opener(request, timeout=8) as response:
                    _range(response, start+offset, end, size)
                    with paths[index].open('ab') as output:
                        while counts[index] < end-start+1:
                            if cancelled() or abort.is_set():
                                return
                            read = getattr(response, 'read1', response.read)
                            data = read(min(64*1024, end-start+1-counts[index]))
                            if not data:
                                raise OSError('分段下载中断')
                            if len(data) > end-start+1-counts[index]:
                                raise ValueError('分段响应超过请求范围')
                            output.write(data)
                            with lock:
                                counts[index] += len(data)
                                progress(sum(counts), size)
                return
            except RangesUnavailable:
                abort.set()
                with lock:
                    errors.append(RangesUnavailable('服务器未支持分段，切换普通下载'))
                return
            except (OSError, ValueError, http.client.HTTPException) as exc:
                if attempt < 2 and not cancelled() and not abort.is_set():
                    sleep(.3*(attempt+1))
                    continue
                abort.set()
                with lock:
                    errors.append(exc)
                return

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='wwbs-download') as pool:
        list(pool.map(worker, range(4)))
    if cancelled():
        raise InterruptedError('更新已取消，下载断点已保留')
    if errors:
        if any(isinstance(error, RangesUnavailable) for error in errors):
            return False
        raise RuntimeError('分段下载中断，已保留断点：'+str(errors[0]))
    if any(length != end-start+1 for length, (start, end) in zip(counts, boundaries)):
        raise RuntimeError('分段下载未完成，已保留断点')
    status('正在合并并校验安装包…')
    combined = folder/'combined.tmp'
    actual = hashlib.sha256()
    with combined.open('wb') as output:
        for path in paths:
            with path.open('rb') as stream:
                while data := stream.read(1024*1024):
                    if cancelled():
                        raise InterruptedError('更新已取消，下载断点已保留')
                    actual.update(data)
                    output.write(data)
    if actual.hexdigest() != checksum:
        combined.unlink(missing_ok=True)
        for path in paths:
            path.unlink(missing_ok=True)
        raise ValueError('分段安装包SHA-256校验失败，已清除损坏分段')
    combined.replace(complete)
    for path in paths:
        path.unlink(missing_ok=True)
    _copy(complete, destination)
    progress(size, size)
    return True
