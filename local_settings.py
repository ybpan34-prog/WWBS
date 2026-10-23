"""Discover other WWBS installations and convert their data without executing them."""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time
import uuid
import zlib

from combat_rotation import validate_store
from windows_client import ClientWindowController


SETTINGS = {
    'combat-settings.json': '战斗键位', 'theme-settings.json': '程序主题',
    'combat-presets.json': '战斗轴、预设与模式分配', 'pet-settings.json': '桌宠选择',
    'pet-display-settings.json': '桌宠大小、显示与行为', 'daily-settings.json': '日常无音区',
    'ui-settings.json': '快捷任务顺序', 'app-settings.json': '任务次数与关机设置',
    'cartethyia-agent-settings.json': '桌宠连接设置', 'weekly_tasks.json': '任务配置',
    'pet-chat-history.json': '桌宠聊天记录', 'aemeath-language-state.json': '桌宠语言状态',
    'connection-settings.json': '窗口、分辨率与设备连接',
    'rain-settings.json': 'Boss战自动播放雨爱（雨量、清晰度与音量）',
}
MAX_SETTINGS_BYTES = 2*1024*1024
VERSION_PATTERN = r'\d+\.\d+\.\d+(?:[ .-]*(?:alpha|beta|rc)[ .-]*\d*)?'


def version_key(value: str):
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', value or '')
    if not match:
        return (0, 0, 0, -1, 0)
    stage = re.search(r'(alpha|beta|rc)[ .-]*(\d*)', value, re.I)
    return (*map(int, match.groups()), {'alpha': 0, 'beta': 1, 'rc': 2}[stage[1].lower()] if stage else 3,
            int(stage[2] or 0) if stage else 0)


def _exe_version(path: Path) -> str:
    # PyInstaller's bounded CArchive script record; read bytes only, never run it.
    try:
        with path.open('rb') as stream:
            size = path.stat().st_size
            start = max(0, size-1024*1024)
            stream.seek(start)
            tail = stream.read()
            marker = tail.rfind(b'MEI\x0c\x0b\n\x0b\x0e')
            if marker < 0 or marker+88 > len(tail):
                return ''
            _magic, length, toc_offset, toc_length, _python, _library = struct.unpack(
                '!8sIIII64s', tail[marker:marker+88])
            base = start+marker+88-length
            if base < 0 or toc_length > 65536:
                return ''
            stream.seek(base+toc_offset)
            toc = stream.read(toc_length)
            offset = 0
            while offset+18 <= len(toc):
                entry_length, position, stored, expanded, compressed, kind = struct.unpack(
                    '!IIIIBc', toc[offset:offset+18])
                if entry_length < 18 or offset+entry_length > len(toc):
                    return ''
                name = toc[offset+18:offset+entry_length].rstrip(b'\0')
                offset += entry_length
                if name != b'app' or kind != b's' or max(stored, expanded) > 4*1024*1024:
                    continue
                if base+position+stored > size:
                    return ''
                stream.seek(base+position)
                data = stream.read(stored)
                if compressed:
                    decoder = zlib.decompressobj()
                    data = decoder.decompress(data, 4*1024*1024+1)
                    if len(data) > 4*1024*1024 or not decoder.eof:
                        return ''
                match = re.search(VERSION_PATTERN.encode(), data, re.I)
                return match[0].decode('ascii') if match else ''
    except (OSError, ValueError, struct.error, zlib.error):
        pass
    return ''


def installation_version(root: Path) -> str:
    for path in (root/'_internal'/'wwbs-version.json', root/'wwbs-version.json'):
        try:
            value = str(json.loads(path.read_text(encoding='utf-8'))['version'])
            if version_key(value)[3] >= 0:
                return value
        except (OSError, ValueError, KeyError, TypeError):
            pass
    version = _exe_version(root/'wwbs.exe')
    if version:
        return version
    try:
        readme = (root/'README.md').read_text(encoding='utf-8')[:4000]
        match = re.search(r'当前源码版本[^\n]*?('+VERSION_PATTERN+')', readme, re.I)
        if match:
            return match[1]
    except (OSError, UnicodeError):
        pass
    match = re.search(VERSION_PATTERN, root.name+' '+root.parent.name, re.I)
    if match:
        return match[0]
    notes = [p.name for p in root.glob('release-notes-v*.md')]
    versions = [m[0] for name in notes if (m := re.search(VERSION_PATTERN, name, re.I))]
    return max(versions, key=version_key) if versions else ''


def settings_files(root: Path) -> dict[str, Path]:
    found = {}
    for name in SETTINGS:
        for base in (root, root/'_internal'):
            path = base/name
            if path.is_file() and not path.is_symlink():
                found[name] = path
                break
    return found


@dataclass(frozen=True)
class Installation:
    root: Path
    version: str
    files: dict[str, Path]


def discover_latest(current: Path, current_version: str, roots: list[Path], *, cancelled=lambda: False,
                    progress=lambda checked, found: None, timeout=30):
    current = current.resolve()
    found, visited = [], set()
    pending = deque((Path(root), 0) for root in roots)
    started, reported = time.monotonic(), 0.0
    while pending and len(visited) < 6000 and not cancelled():
        now = time.monotonic()
        if now-started > timeout:
            raise TimeoutError('本地设置检测超过30秒，已停止。请将用过的旧版本目录放在当前程序目录旁后重试。')
        if now-reported > .2:
            progress(len(visited), len(found))
            reported = now
        folder, depth = pending.popleft()
        try:
            if folder.is_symlink():
                continue
            resolved = folder.resolve()
            if resolved in visited:
                continue
            visited.add(resolved)
            if (folder/'wwbs.exe').is_file():
                if resolved != current:
                    files = settings_files(folder)
                    # Every fresh ZIP contains weekly_tasks.json. It alone is
                    # not evidence of a user's settings and must not outrank
                    # an older installation containing their real preferences.
                    personalized = any(name != 'weekly_tasks.json' for name in files)
                    # Skip unused packages before opening/decompressing their EXE.
                    if not personalized:
                        continue
                    version = installation_version(folder)
                    if personalized and version:
                        found.append(Installation(resolved, version, files))
                continue
            if depth >= 4:
                continue
            for child in folder.iterdir():
                if child.is_dir() and not child.is_symlink() and not child.name.startswith('.') \
                        and child.name.lower() not in {'_internal', '_release-work', 'node_modules',
                                                      'build', 'vendor', '.git', '__pycache__'}:
                    pending.append((child, depth+1))
        except OSError:
            continue
    if not found:
        return None
    def order(installation):
        newest = max((p.stat().st_mtime_ns for p in installation.files.values()), default=0)
        return version_key(installation.version), newest, str(installation.root)
    return max(found, key=order)


def default_search_roots(current: Path) -> list[Path]:
    home = Path.home()
    roots = [current.parent, home/'Downloads', home/'Desktop', home/'Documents']
    if current.parent.parent not in (home, Path(home.anchor)):
        roots.append(current.parent.parent)
    return roots


def convert_settings(name: str, raw):
    if name == 'pet-chat-history.json':
        if not isinstance(raw, dict) or len(raw) > 20:
            raise ValueError('聊天记录格式无效')
        return raw
    if name not in SETTINGS or not isinstance(raw, dict):
        raise ValueError(f'{name}的设置格式无效')
    # Work on a private data copy, preserving keys not yet known to this build.
    data = json.loads(json.dumps(raw, allow_nan=False))
    if name == 'combat-presets.json':
        return validate_store(data)
    if name == 'combat-settings.json':
        for key in ('skill_key', 'ultimate_key'):
            if key in data:
                data[key] = ClientWindowController.normalize_input_binding(str(data[key]))
    elif name == 'theme-settings.json':
        if data.get('theme') not in {'simple', 'daniya', 'aemeath', 'jingran', 'cartethyia'}:
            raise ValueError('无法识别原版本的主题')
        data.update(explicit=True, source='theme-picker')
    elif name == 'pet-settings.json':
        if data.get('pet') not in {'daniya', 'aemeath', 'jingran', 'cartethyia'}:
            raise ValueError('无法识别原版本的桌宠')
    elif name == 'pet-display-settings.json' and 'percent' in data:
        value = float(str(data['percent']).rstrip('%'))
        if not 60 <= value <= 160:
            raise ValueError('桌宠大小超出当前版本支持范围')
        data['percent'] = round(value)
    elif name == 'weekly_tasks.json':
        if not isinstance(data.get('tasks'), list):
            raise ValueError('原版本的任务配置无效')
    elif name == 'cartethyia-agent-settings.json':
        data.pop('api_key', None)
    elif name == 'connection-settings.json':
        if data.get('target_mode', 'client') not in {'client','adb'}:
            raise ValueError('连接模式无效')
        if any(not isinstance(value,str) or len(value)>4096 for value in data.values()):
            raise ValueError('连接设置无效')
    elif name == 'rain-settings.json':
        from rain_effect import normalize_rain_settings
        return normalize_rain_settings(data)
    return data


@dataclass(frozen=True)
class ImportPlan:
    source: Installation
    payloads: dict[str, bytes]
    before: dict[str, bytes | None]


def prepare_import(source: Installation, target: Path) -> ImportPlan:
    payloads, before = {}, {}
    for name, path in source.files.items():
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            raise ValueError(f'{SETTINGS[name]}文件过大，未修改当前设置')
        raw = json.loads(path.read_text(encoding='utf-8'))
        payloads[name] = json.dumps(convert_settings(name, raw), ensure_ascii=False,
                                    indent=2, allow_nan=False).encode('utf-8')
        destination = target/name
        before[name] = destination.read_bytes() if destination.exists() else None
    if not payloads:
        raise ValueError('没有找到可导入的设置')
    return ImportPlan(source, payloads, before)


def apply_import(plan: ImportPlan, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, previous in plan.before.items():
        path = target/name
        actual = path.read_bytes() if path.exists() else None
        if actual != previous:
            raise ValueError('检测后当前设置已改变，请重新检测；未覆盖设置')
    written, temporary, originals = [], [], {}
    restore_failed = False
    try:
        for name, data in plan.payloads.items():
            path = target/(name+'.'+uuid.uuid4().hex+'.tmp')
            path.write_bytes(data)
            temporary.append(path)
            if plan.before[name] is not None:
                original = target/(name+'.'+uuid.uuid4().hex+'.original')
                original.write_bytes(plan.before[name])
                originals[name] = original
        for (name, _data), path in zip(plan.payloads.items(), temporary):
            os.replace(path, target/name)
            written.append(name)
    except OSError as error:
        try:
            for name in reversed(written):
                if plan.before[name] is None:
                    (target/name).unlink(missing_ok=True)
                else:
                    os.replace(originals[name], target/name)
        except OSError as restore_error:
            restore_failed = True
            raise OSError(f'导入未完成且恢复失败，原设置备份保留在{target}的.original文件中：{restore_error}') from error
        raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
        if not restore_failed:
            for path in originals.values():
                path.unlink(missing_ok=True)


def bootstrap_own_settings(current: Path, bundled: Path) -> None:
    """Carry this installation's legacy internal settings into persistent storage."""
    candidates = [bundled]
    try:
        candidates += sorted(current.glob('.wwbs-update-backup-*'),
                             key=lambda p: p.stat().st_mtime_ns, reverse=True)
    except OSError:
        pass
    for candidate in candidates:
        files = {name: path for name, path in settings_files(candidate).items()
                 if not (current/name).exists() and (name != 'weekly_tasks.json' or candidate != bundled)}
        if not files:
            continue
        source = Installation(candidate, installation_version(candidate), files)
        # A corrupt legacy file must not prevent the program from opening.
        for name, path in files.items():
            try:
                plan = prepare_import(Installation(source.root, source.version, {name: path}), current)
                apply_import(plan, current)
            except (OSError, ValueError, TypeError):
                continue


def save_discovery_state(target: Path, version: str, source: str = '') -> None:
    (target/'local-settings-discovery.json').write_text(json.dumps(
        {'checked_version': version, 'source': source, 'checked_at': time.time()},
        ensure_ascii=False), encoding='utf-8')


def discovery_needed(target: Path, version: str) -> bool:
    try:
        return json.loads((target/'local-settings-discovery.json').read_text(
            encoding='utf-8')).get('checked_version') != version
    except (OSError, ValueError, AttributeError):
        return True


def snapshot_settings(current: Path, destination: Path) -> None:
    files = settings_files(current)
    destination.mkdir(parents=True, exist_ok=True)
    for name, path in files.items():
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            raise ValueError(f'{SETTINGS[name]}过大，更新未开始')
        raw = json.loads(path.read_text(encoding='utf-8'))
        (destination/name).write_text(json.dumps(convert_settings(name, raw), ensure_ascii=False,
                                               indent=2, allow_nan=False), encoding='utf-8')


def fingerprint(plan: ImportPlan) -> str:
    return hashlib.sha256(b''.join(name.encode()+data for name, data in sorted(plan.payloads.items()))).hexdigest()


def describe_import(plan: ImportPlan) -> str:
    """Summarize the actual converted data, so a source can be checked before applying."""
    lines = []
    for name, payload in plan.payloads.items():
        data = json.loads(payload)
        detail = ''
        if name == 'theme-settings.json':
            detail = str(data.get('theme', ''))
        elif name == 'combat-settings.json':
            detail = f"技能 {data.get('skill_key', 'E')}；大招 {data.get('ultimate_key', 'R')}"
        elif name == 'combat-presets.json':
            detail = '、'.join(str(p['name']) for p in data['presets'])
        elif name == 'pet-settings.json':
            detail = str(data.get('pet', ''))
        elif name == 'daily-settings.json':
            detail = str(data.get('zone', ''))
        lines.append('• '+SETTINGS[name]+('：'+detail if detail else ''))
    return '\n'.join(lines)


def save_import_receipt(plan: ImportPlan, target: Path) -> None:
    hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in plan.payloads.items()}
    receipt = {'source': str(plan.source.root), 'version': plan.source.version,
               'hashes': hashes, 'pending': True}
    (target/'local-settings-import.json').write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')


def verify_import_receipt(target: Path):
    """Check imported files before UI loaders can write any preferences."""
    path = target/'local-settings-import.json'
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
        if receipt.get('pending') is not True:
            return None
        failed = []
        for name, digest in receipt['hashes'].items():
            if name not in SETTINGS:
                raise ValueError('本地设置导入记录无效')
            try:
                matches = hashlib.sha256((target/name).read_bytes()).hexdigest() == digest
            except OSError:
                matches = False
            if not matches:
                failed.append(SETTINGS[name])
        receipt.update(pending=False, failed=failed)
        path.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
        return receipt
    except FileNotFoundError:
        return None


def changed_settings(plan: ImportPlan) -> list[str]:
    """Compare JSON values, ignoring whitespace; never treat a no-op as migration."""
    changed = []
    for name, payload in plan.payloads.items():
        previous = plan.before.get(name)
        try:
            equal = previous is not None and json.loads(previous) == json.loads(payload)
        except (ValueError, UnicodeError):
            equal = False
        if not equal:
            changed.append(name)
    return changed
