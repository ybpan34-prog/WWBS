"""Validate an onedir release before quitting; preserve user data during install."""
import hashlib
import http.client
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
import tempfile
import sys
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote, urlsplit, urlunsplit

from local_settings import SETTINGS
from update_transfer import download_ranges


def create_update_work(target: Path) -> Path:
    path = target/('.wwbs-update-work-'+uuid.uuid4().hex)
    try:
        path.mkdir()
    except OSError as exc:
        raise OSError('当前安装目录不可写，请以管理员身份运行软件后更新。原程序未改动。') from exc
    return path


def refresh_release_asset(asset, tag, *, opener=urllib.request.urlopen, cancelled=lambda: False):
    """Refresh an asset by release tag, including its immutable ID and checksum."""
    parts=urlsplit(str(asset.get('browser_download_url','')))
    path=re.fullmatch(r'/([^/]+)/([^/]+)/releases/download/[^/]+/([^/]+)',parts.path)
    if parts.scheme!='https' or parts.hostname!='github.com' or not path:
        raise ValueError('安装包下载地址无效')
    if cancelled():
        raise InterruptedError('更新已取消，原程序未改动')
    url=f'https://api.github.com/repos/{path[1]}/{path[2]}/releases/tags/{quote(tag,safe="")}?wwbs_update={time.time_ns()}'
    request=urllib.request.Request(url,headers={'User-Agent':'WWBS/updater','Cache-Control':'no-cache',
                                               'Accept':'application/vnd.github+json'})
    try:
        with opener(request,timeout=8) as response:
            raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:
            raise ValueError('版本信息过大')
        release=json.loads(raw)
        if not isinstance(release,dict) or release.get('tag_name')!=tag or release.get('draft'):
            raise ValueError('版本信息不一致')
        name=asset.get('name') or path[3]
        fresh=next((item for item in release.get('assets',[]) if item.get('name')==name and item.get('state')=='uploaded'),None)
        if fresh is None:
            raise ValueError('当前版本的安装包尚未上传完成，请稍后重试')
        return dict(fresh)
    except (urllib.error.URLError,OSError,http.client.HTTPException,ValueError) as exc:
        raise RuntimeError('刷新安装包信息失败：'+str(exc)) from exc


def download_asset(asset: dict, destination: Path, *, version: str, progress=lambda *_: None,
                   cancelled=lambda: False, opener=urllib.request.urlopen, sleep=time.sleep,
                   refresh=None, cache_dir=None, status=lambda _text: None) -> dict:
    asset=dict(asset)
    errors = []
    restart=False
    ranges=True
    for attempt in range(3):
        if cancelled():
            raise InterruptedError('更新已取消，原程序未改动')
        expected = int(asset.get('size') or 0)
        if expected < 0 or expected > 512*1024*1024:
            raise ValueError('安装包大小不符合预期')
        base = str(asset['browser_download_url'])
        parts = urlsplit(base)
        if parts.scheme != 'https' or parts.hostname not in {'github.com', 'api.github.com'}:
            raise ValueError('安装包下载地址无效')
        if ranges:
            try:
                parallel_asset=asset
                api=urlsplit(str(asset.get('url','')))
                if attempt == 1 and api.scheme == 'https' and api.hostname == 'api.github.com':
                    parallel_asset=dict(asset, browser_download_url=asset['url'])
                if download_ranges(parallel_asset, destination, version=version, progress=progress,
                        cancelled=cancelled, opener=opener, sleep=sleep,
                        cache_dir=cache_dir or destination.parent/'.wwbs-download-cache', status=status):
                    return asset
                ranges=False
            except InterruptedError:
                raise
            except (OSError, RuntimeError, ValueError, http.client.HTTPException) as exc:
                errors.append(str(exc))
                if attempt == 2:
                    break
                if refresh is not None:
                    try:
                        asset=dict(refresh())
                    except InterruptedError:
                        raise
                    except (OSError, RuntimeError, ValueError):
                        pass
                sleep(.5*(attempt+1))
                continue
        query = parts.query+('&' if parts.query else '')+'wwbs_update='+str(time.time_ns())
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ''))
        headers = {'User-Agent': 'wwbs/'+version, 'Cache-Control': 'no-cache',
                   'Accept': 'application/octet-stream', 'Accept-Encoding':'identity'}
        offset=destination.stat().st_size if attempt and destination.exists() and not restart else 0
        if offset and (not expected or offset>=expected):
            offset=0
        if offset:
            headers['Range']=f'bytes={offset}-'
        # The release-asset API is a second official download entry point.
        if attempt == 1 and asset.get('url'):
            api = urlsplit(str(asset['url']))
            if api.scheme == 'https' and api.hostname == 'api.github.com':
                query=api.query+('&' if api.query else '')+'wwbs_update='+str(time.time_ns())
                url = urlunsplit((api.scheme,api.netloc,api.path,query,''))
        request = urllib.request.Request(url, headers=headers)
        try:
            with opener(request, timeout=30) as response:
                status=getattr(response,'status',200)
                if status==206:
                    content_range=response.headers.get('Content-Range','')
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',content_range)
                    if (not match or int(match[1])!=offset or int(match[2])<offset
                            or int(match[2])>=int(match[3]) or (expected and int(match[3])!=expected)):
                        raise ValueError('断点下载范围不一致')
                else:
                    offset=0  # A server may ignore Range: safely restart.
                restart=False
                progress(offset, expected)
                total=offset
                with destination.open('ab' if offset else 'wb') as output:
                    while True:
                        if cancelled():
                            raise InterruptedError('更新已取消，原程序未改动')
                        read = getattr(response, 'read1', response.read)
                        data = read(64*1024)
                        if not data:
                            break
                        prefix = data[:max(0, 4-total)]
                        if total < 4 and prefix != b'PK\x03\x04'[total:total+len(prefix)]:
                            restart=True
                            raise ValueError('下载入口未返回ZIP安装包')
                        total += len(data)
                        if total > (expected or 512*1024*1024):
                            restart=True
                            raise ValueError('下载内容超过安装包标记大小')
                        output.write(data)
                        progress(total, expected)
            if not total or (expected and total != expected):
                raise ValueError('安装包下载不完整')
            digest=asset.get('digest') or ''
            if digest:
                if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest):
                    raise ValueError('无法识别更新包校验格式')
                with destination.open('rb') as stream:
                    actual=hashlib.file_digest(stream,'sha256').hexdigest()
                if actual!=digest.split(':',1)[1].lower():
                    restart=True
                    raise ValueError('安装包SHA-256校验失败')
            return asset
        except InterruptedError:
            raise
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
            errors.append(str(exc))
            if attempt < 2:
                if refresh is not None:
                    try:
                        fresh=refresh()
                        if any(fresh.get(key)!=asset.get(key) for key in ('id','size','digest')):
                            restart=True
                        asset=dict(fresh)
                    except InterruptedError:
                        raise
                    except (RuntimeError,OSError,ValueError) as refresh_error:
                        errors.append(str(refresh_error))
                sleep(.5*(attempt+1))
    raise RuntimeError('安装包下载失败（已重试3次）：'+errors[-1])


def signal_update_ready() -> None:
    """A new process acknowledges only after its main GUI has initialized."""
    filename = os.environ.pop("WWBS_UPDATE_READY", "")
    token = os.environ.pop("WWBS_UPDATE_TOKEN", "")
    if not filename or not re.fullmatch(r"[0-9a-f]{32}", token):
        return
    path = Path(filename).resolve()
    temporary = (path.parent.name.startswith('wwbs_update_')
                 and path.parent.parent == Path(tempfile.gettempdir()).resolve())
    beside_app = (re.fullmatch(r'\.wwbs-update-work-[0-9a-f]{32}', path.parent.name)
                  and getattr(sys, 'frozen', False)
                  and path.parent.parent == Path(sys.executable).resolve().parent)
    if path.name != 'ready' or not (temporary or beside_app):
        return
    path.write_text(token, encoding="ascii")


def prepare_update(archive: Path, destination: Path, expected_size=0, digest="") -> Path:
    if expected_size and archive.stat().st_size != expected_size:
        raise ValueError("更新包大小不符，下载可能不完整，原程序未改动。")
    if digest:
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            raise ValueError("无法识别更新包校验格式。")
        with archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest.split(":", 1)[1].lower():
            raise ValueError("更新包 SHA-256 校验失败，原程序未改动。")
    with zipfile.ZipFile(archive) as package:
        seen = set()
        total = 0
        for item in package.infolist():
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or any(p in {"..", "."} or ":" in p
                    or p.endswith((" ", ".")) for p in parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError("更新包含不安全路径。")
            key = name.rstrip("/").casefold()
            if key in seen:
                raise ValueError("更新包含重复路径。")
            seen.add(key)
            total += item.file_size
            if total > 2 * 1024 ** 3:
                raise ValueError("更新包解压大小超出限制。")
        bad = package.testzip()
        if bad:
            raise ValueError("更新包 CRC 校验失败。")
        package.extractall(destination)
    roots = [p.parent for p in destination.rglob("wwbs.exe")]
    roots = [p for p in roots if (p / "_internal" / "base_library.zip").is_file()
             and any((p / "_internal").glob("python3*.dll"))]
    if len(roots) != 1:
        raise ValueError("更新包必须包含唯一的 wwbs.exe 和完整 _internal 运行库。")
    return roots[0]


def install_script(staged: Path, target: Path, work: Path, process_id: int, notify_failure: bool = True) -> str:
    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"
    # Keep backups and logs even after a successful start. No recursive deletion.
    return f"""$ErrorActionPreference = 'Stop'
$source = {quote(staged.resolve())}
$target = {quote(target.resolve())}
$work = {quote(work.resolve())}
$log = Join-Path $work 'update.log'
$backup = Join-Path $target ('.wwbs-update-backup-' + [guid]::NewGuid().ToString('N'))
$old = @()
$installed = @()
$settingNames = @({', '.join(quote(Path(name)) for name in SETTINGS)})
$settingsSource = Join-Path $work 'settings'
$oldSettings = @()
$settingsBackedUp = $false
try {{
    $deadline = (Get-Date).AddSeconds(90)
    while (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue) {{
        if ((Get-Date) -gt $deadline) {{ throw 'Old process did not exit; update cancelled.' }}
        Start-Sleep -Milliseconds 500
    }}
    New-Item -ItemType Directory -Path $backup | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $backup 'settings') | Out-Null
    foreach ($name in $settingNames) {{
        $path = Join-Path $target $name
        if (Test-Path -LiteralPath $path) {{
            Copy-Item -LiteralPath $path -Destination (Join-Path (Join-Path $backup 'settings') $name)
            $oldSettings += $name
        }}
    }}
    $settingsBackedUp = $true
    foreach ($name in @('wwbs.exe', '_internal')) {{
        $dest = [IO.Path]::GetFullPath((Join-Path $target $name))
        $prefix = [IO.Path]::GetFullPath($target).TrimEnd('\\') + '\\'
        if (-not $dest.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {{ throw 'Unsafe target path' }}
        if (Test-Path -LiteralPath $dest) {{
            Move-Item -LiteralPath $dest -Destination (Join-Path $backup $name)
            $old += $name
        }}
        $installed += $name
        Copy-Item -LiteralPath (Join-Path $source $name) -Destination $dest -Recurse
    }}
    foreach ($name in $settingNames) {{
        $saved = Join-Path $settingsSource $name
        if (Test-Path -LiteralPath $saved) {{
            Copy-Item -LiteralPath $saved -Destination (Join-Path $target $name) -Force
        }}
    }}
    $exe = Join-Path $target 'wwbs.exe'
    $env:WWBS_UPDATE_READY = Join-Path $work 'ready'
    $env:WWBS_UPDATE_TOKEN = [guid]::NewGuid().ToString('N')
    $child = Start-Process -FilePath $exe -WorkingDirectory $target -WindowStyle Normal -PassThru
    $deadline = (Get-Date).AddSeconds(45)
    while ($true) {{
        if ($child.HasExited) {{ throw 'New process exited during startup.' }}
        if ((Test-Path -LiteralPath $env:WWBS_UPDATE_READY) -and
            (([IO.File]::ReadAllText($env:WWBS_UPDATE_READY)) -eq $env:WWBS_UPDATE_TOKEN)) {{ break }}
        if ((Get-Date) -gt $deadline) {{ throw 'New GUI did not acknowledge startup within 45 seconds.' }}
        Start-Sleep -Milliseconds 250
    }}
    "Update copied and process started. Backup: $backup" | Out-File -LiteralPath $log -Encoding utf8
}} catch {{
    $failure = $_.ToString()
    try {{
        if ($child -and -not $child.HasExited) {{ $child.Kill(); $child.WaitForExit() }}
        foreach ($name in $installed) {{
            $dest = Join-Path $target $name
            if (Test-Path -LiteralPath $dest) {{
                Move-Item -LiteralPath $dest -Destination (Join-Path $backup ('failed-' + $name))
            }}
        }}
        foreach ($name in $old) {{
            Move-Item -LiteralPath (Join-Path $backup $name) -Destination (Join-Path $target $name)
        }}
        if ($settingsBackedUp) {{ foreach ($name in $settingNames) {{
            $path = Join-Path $target $name
            if ($oldSettings -contains $name) {{
                Copy-Item -LiteralPath (Join-Path (Join-Path $backup 'settings') $name) -Destination $path -Force
            }} elseif ((Test-Path -LiteralPath $path) -and $backup -and (Test-Path -LiteralPath $backup)) {{
                Move-Item -LiteralPath $path -Destination (Join-Path $backup ('failed-' + $name))
            }}
        }} }}
        $failure += "`nOriginal files restored. Please restart WWBS manually."
    }} catch {{ $failure += "`nRollback incomplete: " + $_.ToString() }}
    $failure | Out-File -LiteralPath $log -Encoding utf8
    if ({'$true' if notify_failure else '$false'}) {{
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("Update failed. Log: $log`n$failure", 'WWBS update') | Out-Null
    }}
    exit 1
}}
"""
