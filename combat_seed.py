"""Offline, versioned sharing codes for a single combat preset.

Compatibility contract: future releases must retain all published decoders and
their original semantics. New wire layouts require a new prefix. Do not change
fixed action indexes, defaults or dictionaries; run the saved historical seed
fixtures before release, independently of the current app defaults.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import hashlib
import json
import itertools
import re
import struct
import uuid
import zlib

from combat_rotation import COMBAT_MODES, MAX_PRESET_NAME, validate_store


PREFIX = "WWBS1"
SHORT_PREFIX = "WWBS2"
COMPACT_PREFIX = "WWBS3"
NAMED_PREFIX = 'WWBS4.'
LEGACY_NAMED_PREFIX = '4.'
EXTENDED_NAMED_PREFIX = 'WWBS5.'
MAX_SEED_NAME = 10
# Frozen WWBS4 data layout: name flag, order, times and action headers.
NAMED_DICT = bytes.fromhex('00000019000f00050f00050607086901232569011422292269011e27690150600064')
# Frozen default payload (without the random identifier). Never derive this
# dictionary from the app's current defaults: old seeds must stay compatible.
SHORT_DICT = bytes.fromhex("000fe9bb98e8aea4e68898e69697e8bdb40019000f00050f00050607086901232569011422292269011e27690150600064")
MAX_SEED_CHARS = 24000
MAX_PAYLOAD_BYTES = 32768
# These format defaults and action indexes are fixed for WWBS2 compatibility.
SHORT_ACTIONS = (
    ("idle_attack", 20, 0), ("attack_count", 15, 0), ("jump_attack", 3, 0),
    ("attack_seconds", 3, 0), ("heavy_count", 1, 0), ("skill", 1, 5),
    ("ultimate", 1, 15), ("echo", 1, 20), ("approach", .09, .75), ("wait", 1, 0),
)
SHORT_ORDERS = tuple(itertools.permutations((1, 2, 3)))
EXTENDED_ACTIONS = SHORT_ACTIONS + (("execute", 1, 0), ("skill_count", 1, 0), ("ultimate_count", 1, 0))


def _checked_preset(preset: dict) -> dict:
    return validate_store({"version": 5, "active": preset["id"], "presets": [preset]})["presets"][0]


def _uint(value: int) -> bytes:
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _number(value) -> bytes:
    if value == int(value):
        return b"\x00" + _uint(int(value))
    cents = round(value * 100)
    if cents / 100 == value:
        return b"\x01" + _uint(cents)
    return b"\x02" + struct.pack("<d", value)


def _export_third_generation(preset: dict) -> str:
    checked = _checked_preset(preset)
    name = checked["name"].encode("utf-8")
    raw = bytearray(uuid.uuid4().bytes)
    raw.append(SHORT_ORDERS.index(tuple(checked["slot_order"])))
    raw.extend(_uint(len(name)))
    raw.extend(name)
    for slot in (1, 2, 3):
        raw.extend(_number(checked["slot_times"][str(slot)]))
    raw.extend(_uint(len(checked["modules"])))
    kinds = [spec[0] for spec in SHORT_ACTIONS]
    for item in checked["modules"]:
        index = kinds.index(item["kind"])
        _, value, interval = SHORT_ACTIONS[index]
        header = index | ((item["slot"]-1) << 4)
        if item["value"] != value:
            header |= 64
        if item["interval"] != interval:
            header |= 128
        raw.append(header)
        if header & 64:
            raw.extend(_number(item["value"]))
        if header & 128:
            raw.extend(_number(item["interval"]))
    compressed = zlib.compress(raw, 9)
    compressor = zlib.compressobj(9, zdict=SHORT_DICT)
    dictionary_compressed = compressor.compress(raw) + compressor.flush()
    candidates = [b"\x00"+raw, b"\x01"+compressed, b"\x02"+dictionary_compressed]
    if raw[16:] == SHORT_DICT:
        candidates.append(b"\x03"+raw[:16])
    body = min(candidates, key=len)
    packet = body + hashlib.sha256(body).digest()[:8]
    return COMPACT_PREFIX + "." + base64.urlsafe_b64encode(packet).decode("ascii").rstrip("=")


def validate_seed_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_SEED_NAME:
        raise ValueError('种子名称须为1到10个字')
    name = name.strip()
    if any(ord(character) < 32 or character in '【】' for character in name):
        raise ValueError('种子名称不能包含换行或【】')
    return name


def export_seed(preset: dict, *, seed_name: str | None = None) -> str:
    checked = _checked_preset(preset)
    extended = any(item['kind'] in {'execute', 'skill_count', 'ultimate_count'} for item in checked['modules'])
    actions = EXTENDED_ACTIONS if extended else SHORT_ACTIONS
    automatic_name = re.sub(r'[【】\x00-\x1f]', '', checked['name']).strip()[:MAX_SEED_NAME] or '战斗轴'
    alias = validate_seed_name(seed_name if seed_name is not None else automatic_name)
    # Keep the original preset name when it differs from the short display name.
    raw = bytearray([int(alias != checked['name'])])
    if raw[0]:
        name = checked['name'].encode('utf-8')
        raw.extend(_uint(len(name)))
        raw.extend(name)
    raw.append(SHORT_ORDERS.index(tuple(checked['slot_order'])))
    for slot in (1, 2, 3):
        raw.extend(_number(checked['slot_times'][str(slot)]))
    raw.extend(_uint(len(checked['modules'])))
    kinds = [row[0] for row in actions]
    for item in checked['modules']:
        index = kinds.index(item['kind'])
        _, value, interval = actions[index]
        header = index | ((item['slot']-1) << 4)
        header |= 64 if item['value'] != value else 0
        header |= 128 if item['interval'] != interval else 0
        raw.append(header)
        if header & 64:
            raw.extend(_number(item['value']))
        if header & 128:
            raw.extend(_number(item['interval']))
    compressor = zlib.compressobj(9, wbits=-15, zdict=NAMED_DICT)
    compressed = compressor.compress(raw)+compressor.flush()
    choices = [(0, bytes(raw)), (1, compressed)]
    if raw == NAMED_DICT:
        choices.append((2, b''))
    mode, data = min(choices, key=lambda item: len(item[1]))
    body = bytes([mode])+uuid.uuid4().bytes[:12]+data
    packet = body+struct.pack('<I', zlib.crc32(alias.encode('utf-8')+body))
    return f'【{alias}】'+(EXTENDED_NAMED_PREFIX if extended else NAMED_PREFIX)+base64.urlsafe_b64encode(packet).decode().rstrip('=')


def _decode_named(name: str, content: str, actions=SHORT_ACTIONS) -> dict:
    name = validate_seed_name(name)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', content):
        raise ValueError('种子格式错误')
    packet = base64.b64decode(content+'='*(-len(content)%4), altchars=b'-_', validate=True)
    if base64.urlsafe_b64encode(packet).decode().rstrip('=') != content or len(packet) < 17:
        raise ValueError('种子内容不完整')
    body = packet[:-4]
    if struct.unpack('<I', packet[-4:])[0] != zlib.crc32(name.encode('utf-8')+body):
        raise ValueError('种子校验失败，内容可能不完整或被改动')
    mode, identifier, raw = body[0], body[1:13].hex(), body[13:]
    if mode == 2:
        if raw:
            raise ValueError('种子默认轴格式错误')
        raw = NAMED_DICT
    elif mode == 1:
        inflater = zlib.decompressobj(wbits=-15, zdict=NAMED_DICT)
        raw = inflater.decompress(raw, MAX_PAYLOAD_BYTES+1)
        if len(raw) > MAX_PAYLOAD_BYTES or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
            raise ValueError('种子压缩格式错误')
    elif mode != 0:
        raise ValueError('不支持这个种子内容版本')
    reader = _Reader(raw)
    name_flag = reader.take(1)[0]
    if name_flag == 1:
        length = reader.uint()
        if not 1 <= length <= MAX_PRESET_NAME*4:
            raise ValueError('原预设名称过长')
        preset_name = reader.take(length).decode('utf-8')
    elif name_flag == 0:
        preset_name = name
    else:
        raise ValueError('种子名称格式错误')
    order = reader.take(1)[0]
    if order >= len(SHORT_ORDERS):
        raise ValueError('种子角色顺序无效')
    times = {str(slot): reader.number() for slot in (1, 2, 3)}
    count = reader.uint()
    if not 1 <= count <= 100:
        raise ValueError('种子须包含1到100个模块')
    modules = []
    for _ in range(count):
        header = reader.take(1)[0]
        index, slot = header & 15, ((header >> 4) & 3)+1
        if index >= len(actions) or slot > 3:
            raise ValueError('种子模块类型或角色位无效')
        kind, value, interval = actions[index]
        modules.append({'id': uuid.uuid4().hex, 'kind': kind, 'slot': slot,
                        'value': reader.number() if header & 64 else value,
                        'interval': reader.number() if header & 128 else interval})
    if reader.offset != len(raw):
        raise ValueError('种子包含无法识别的内容')
    preset = _checked_preset({'id': uuid.uuid4().hex, 'name': preset_name,
                             'slot_order': list(SHORT_ORDERS[order]), 'slot_times': times, 'modules': modules})
    preset.update(share_id=identifier, seed_name=name)
    return preset


class _Reader:
    def __init__(self, raw):
        self.raw, self.offset = raw, 0

    def take(self, count):
        if self.offset + count > len(self.raw):
            raise ValueError("种子内容不完整")
        result = self.raw[self.offset:self.offset+count]
        self.offset += count
        return result

    def uint(self):
        result = 0
        for shift in range(0, 35, 7):
            value = self.take(1)[0]
            result |= (value & 127) << shift
            if not value & 128:
                return result
        raise ValueError("种子数字格式错误")

    def number(self):
        tag = self.take(1)[0]
        if tag == 0:
            return self.uint()
        if tag == 1:
            return self.uint() / 100
        if tag == 2:
            return struct.unpack("<d", self.take(8))[0]
        raise ValueError("种子数字格式错误")


def _inflate(compressed, *, dictionary=False):
    inflater = zlib.decompressobj(zdict=SHORT_DICT) if dictionary else zlib.decompressobj()
    decoded = inflater.decompress(compressed, MAX_PAYLOAD_BYTES + 1)
    if len(decoded) > MAX_PAYLOAD_BYTES or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ValueError("种子内容过大或压缩格式错误")
    return decoded


def _decode_short(content, *, compact=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", content):
        raise ValueError("种子格式错误")
    packet = base64.b64decode(content + "=" * (-len(content) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(packet).decode("ascii").rstrip("=") != content:
        raise ValueError("种子格式错误")
    if len(packet) < 10 or hashlib.sha256(packet[:-8]).digest()[:8] != packet[-8:]:
        raise ValueError("种子校验失败，内容可能不完整或被改动")
    body = packet[:-8]
    if body[0] not in ((0, 1, 2, 3) if compact else (0, 1)):
        raise ValueError("不支持这个种子内容版本")
    if body[0] == 3:
        if len(body) != 17:
            raise ValueError("种子内容不完整")
        raw = body[1:] + SHORT_DICT
    elif body[0] in (1, 2):
        raw = _inflate(body[1:], dictionary=body[0] == 2)
    else:
        raw = body[1:]
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("种子内容过大")
    reader = _Reader(raw)
    share_id = reader.take(16).hex()
    order = reader.take(1)[0]
    if order >= len(SHORT_ORDERS):
        raise ValueError("种子角色顺序无效")
    length = reader.uint()
    if length > MAX_PRESET_NAME * 4:
        raise ValueError("种子名称过长")
    name = reader.take(length).decode("utf-8")
    times = {str(n): reader.number() for n in (1, 2, 3)}
    count = reader.uint()
    if not 1 <= count <= 100:
        raise ValueError("种子须包含1到100个模块")
    modules = []
    for _ in range(count):
        header = reader.take(1)[0]
        index, slot = header & 15, ((header >> 4) & 3)+1
        if index >= len(SHORT_ACTIONS) or slot > 3:
            raise ValueError("种子模块类型或角色位无效")
        kind, value, interval = SHORT_ACTIONS[index]
        modules.append({"id": uuid.uuid4().hex, "kind": kind, "slot": slot,
                        "value": reader.number() if header & 64 else value,
                        "interval": reader.number() if header & 128 else interval})
    if reader.offset != len(raw):
        raise ValueError("种子包含无法识别的内容")
    preset = _checked_preset({"id": uuid.uuid4().hex, "name": name, "slot_times": times,
                              "slot_order": list(SHORT_ORDERS[order]), "modules": modules})
    preset["share_id"] = share_id
    return preset


def decode_seed(seed: str) -> dict:
    """Validate and decode data only; nothing from a seed is executable."""
    try:
        if not isinstance(seed, str) or len(seed) > MAX_SEED_CHARS * 2:
            raise ValueError("种子过长")
        # Only wrapper/body formatting is unconditionally discarded. An old
        # seed's original name may legitimately contain a zero-width character.
        formatting = r'[\u200b-\u200f\u2060\ufeff]'
        seed = re.sub(r'^(?:\s|'+formatting+r')+|(?:\s|'+formatting+r')+$', '', seed)
        if seed.startswith('【'):
            end = seed.find('】')
            if end < 0:
                raise ValueError('种子名称不完整')
            name = seed[1:end].replace('\r', '').replace('\n', '').replace('\t', '')
            body = re.sub(formatting, '', ''.join(seed[end+1:].split()))
            for prefix, actions in ((EXTENDED_NAMED_PREFIX, EXTENDED_ACTIONS),
                                    (NAMED_PREFIX, SHORT_ACTIONS), (LEGACY_NAMED_PREFIX, SHORT_ACTIONS)):
                if body.startswith(prefix):
                    try:
                        return _decode_named(name, body[len(prefix):], actions)
                    except ValueError:
                        cleaned_name = re.sub(formatting, '', name)
                        if cleaned_name == name:
                            raise
                        return _decode_named(cleaned_name, body[len(prefix):], actions)
            raise ValueError('不支持这个种子版本，请升级程序')
        seed = re.sub(formatting, '', "".join(seed.split()))
        if len(seed) > MAX_SEED_CHARS:
            raise ValueError("种子过长")
        if seed.startswith(COMPACT_PREFIX + "."):
            return _decode_short(seed[len(COMPACT_PREFIX)+1:], compact=True)
        if seed.startswith(SHORT_PREFIX + "."):
            return _decode_short(seed[len(SHORT_PREFIX)+1:])
        parts = seed.split(".")
        if len(parts) != 3:
            raise ValueError("请粘贴完整的 WWBS 种子")
        prefix, content, checksum = parts
        if prefix != PREFIX:
            raise ValueError("不支持这个种子版本，请检查种子或升级程序")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", content) or not re.fullmatch(r"[0-9a-f]{16}", checksum):
            raise ValueError("种子格式错误")
        compressed = base64.b64decode(content + "=" * (-len(content) % 4), altchars=b"-_", validate=True)
        if hashlib.sha256(compressed).hexdigest()[:16] != checksum:
            raise ValueError("种子校验失败，内容可能不完整或被改动")
        decoded = _inflate(compressed)
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != 1 or type(payload.get("v")) is not int:
            raise ValueError("不支持这个种子内容版本")
        if set(payload) != {"v", "uid", "n", "o", "t", "m"}:
            raise ValueError("种子内容格式错误")
        if not isinstance(payload["uid"], str) or not re.fullmatch(r"[0-9a-f]{32}", payload["uid"]):
            raise ValueError("种子标识无效")
        if not isinstance(payload["n"], str) or not isinstance(payload["t"], list) or len(payload["t"]) != 3:
            raise ValueError("种子名称或驻场时间格式错误")
        rows = payload["m"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError("种子须包含1到100个模块")
        if any(type(value) not in (int, float) for value in payload["t"]):
            raise ValueError("种子驻场时间必须是数字")
        modules = []
        for row in rows:
            if (not isinstance(row, list) or len(row) != 4 or not isinstance(row[0], str)
                    or type(row[1]) is not int or any(type(v) not in (int, float) for v in row[2:])):
                raise ValueError("种子模块格式错误")
            modules.append({"id": uuid.uuid4().hex, "kind": row[0], "slot": row[1],
                            "value": row[2], "interval": row[3]})
        preset = _checked_preset({
            "id": uuid.uuid4().hex, "name": payload["n"], "slot_order": payload["o"],
            "slot_times": {str(n): value for n, value in enumerate(payload["t"], 1)}, "modules": modules,
        })
        preset["share_id"] = payload["uid"]
        return preset
    except (TypeError, KeyError, OverflowError, RecursionError, zlib.error, UnicodeError,
            binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("种子内容无效，请检查是否复制完整") from exc


def import_seed(store: dict, seed: str, *, modes=()) -> tuple[dict, str]:
    checked = validate_store(store)
    if len(checked["presets"]) >= 30:
        raise ValueError("预设数量已满，最多保存30个预设")
    if any(mode not in COMBAT_MODES for mode in modes):
        raise ValueError("请选择有效的使用模式")
    preset = decode_seed(seed)
    names = {p["name"] for p in checked["presets"]}
    base = re.sub(r"（导入）(?:（\d+）)?$", "", preset["name"]) or preset["name"]
    preset["name"] = base[:MAX_PRESET_NAME-4] + "（导入）"
    index = 2
    while preset["name"] in names:
        suffix = f"（导入）（{index}）"
        preset["name"] = base[:MAX_PRESET_NAME-len(suffix)].rstrip() + suffix
        index += 1
    result = deepcopy(checked)
    result["presets"].append(preset)
    result["active"] = preset["id"]
    for mode in modes:
        result["modes"][mode] = preset["id"]
    return validate_store(result), preset["id"]
