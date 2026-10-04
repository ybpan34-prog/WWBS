"""Validated, ordered combat action presets shared by daily and 4C battles."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import uuid
import threading
import time


ACTION_SPECS = {
    "idle_attack": ("空闲时持续普攻", "其他模块结束后普攻，每 N 下穿插重击", 1, 100),
    "attack_count": ("普攻 N 次", "按节奏点击左键 N 次", 1, 100),
    "jump_attack": ("跳跃普攻", "跳跃后普攻 N 次", 1, 20),
    "attack_seconds": ("普攻 N 秒", "按顺序执行的普攻时长", 0.2, 30),
    "heavy_count": ("重击 N 次", "长按左键进行重击", 1, 20),
    "skill": ("施放技能", "使用任务设置中的技能键", 1, 5),
    "ultimate": ("施放大招", "使用任务设置中的大招键", 1, 5),
    "echo": ("施放声骸 Q", "施放当前角色的声骸技能", 1, 5),
    "approach": ("向前靠近", "按住 W 靠近目标", 0.05, 3),
    "wait": ("等待 N 秒", "按顺序等待，仍检查战斗结束", 0.2, 30),
}

DEFAULT_VALUES = {
    "idle_attack": (15, 0), "attack_count": (15, 0), "jump_attack": (3, 0),
    "attack_seconds": (3, 0), "heavy_count": (1, 0),
    "skill": (1, 10), "ultimate": (1, 15), "echo": (1, 20),
    "approach": (0.09, 0.75), "wait": (1, 0),
}
COMBAT_MODES = {"combat_4c": "4C 刷取", "daily": "一键日常"}
SLOT_NAMES = {1: "一号位", 2: "二号位", 3: "三号位"}


def new_module(kind: str, slot: int = 1) -> dict:
    if kind not in ACTION_SPECS:
        raise ValueError("未知战斗模块")
    value, interval = DEFAULT_VALUES[kind]
    if slot not in SLOT_NAMES:
        raise ValueError("角色位须为一号位、二号位或三号位")
    return {"id": uuid.uuid4().hex[:12], "kind": kind, "value": value, "interval": interval, "slot": slot}


def default_store() -> dict:
    modules = [new_module(kind) for kind in
               ("skill", "ultimate", "echo", "approach", "idle_attack")]
    # The former healing combo is editable through ordinary third-slot modules.
    for kind, value in (("wait", .35), ("skill", 1), ("wait", .2),
                        ("jump_attack", 3), ("wait", 1), ("jump_attack", 3),
                        ("wait", .3), ("echo", 1), ("wait", .8), ("idle_attack", 100)):
        item = new_module(kind, 3)
        item["value"] = value
        modules.append(item)
    return {"version": 3, "active": "default", "modes": {mode: "default" for mode in COMBAT_MODES}, "presets": [
        {"id": "default", "name": "默认战斗轴", "slot_times": {"1": 5, "2": 5, "3": 8}, "modules": modules},
    ]}


def validate_store(raw) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("presets"), list):
        raise ValueError("战斗排轴配置格式错误")
    presets = []
    seen_presets = set()
    seen_names = set()
    for source in raw["presets"]:
        if not isinstance(source, dict):
            raise ValueError("战斗预设格式错误")
        preset_id = str(source.get("id", ""))
        name = str(source.get("name", "")).strip()
        if not preset_id or preset_id in seen_presets or not name or name in seen_names or len(name) > 40:
            raise ValueError("战斗预设名称或标识无效")
        seen_presets.add(preset_id)
        seen_names.add(name)
        modules = []
        seen_modules = set()
        for entry in source.get("modules", []):
            if not isinstance(entry, dict):
                raise ValueError("战斗模块格式错误")
            kind = entry.get("kind")
            if kind == "continuous":
                kind = "idle_attack"
            # beta2's fixed healing macro is retired; all actions now have a slot.
            if kind == "heal" and raw.get("version", 1) == 1:
                continue
            if kind not in ACTION_SPECS:
                raise ValueError(f"未知战斗模块：{kind}")
            module_id = str(entry.get("id", ""))
            if not module_id or module_id in seen_modules:
                raise ValueError("战斗模块标识重复")
            seen_modules.add(module_id)
            value = float(entry.get("value", 0))
            low, high = ACTION_SPECS[kind][2:]
            interval = float(entry.get("interval", 0))
            if raw.get("version", 1) == 1 and preset_id == "default":
                if kind == "idle_attack" and value == 10:
                    value = 15.0
                if kind == "ultimate" and interval == 10:
                    interval = 15.0
            if not math.isfinite(value) or not math.isfinite(interval) or not low <= value <= high or not 0 <= interval <= 120:
                raise ValueError(f"{ACTION_SPECS[kind][0]}参数超出范围")
            if kind in {"skill", "ultimate", "echo", "approach"} and interval < 0.2:
                raise ValueError(f"{ACTION_SPECS[kind][0]}的执行间隔至少为 0.2 秒")
            if kind in {"idle_attack", "attack_count", "jump_attack", "heavy_count", "skill", "ultimate", "echo"} and not value.is_integer():
                raise ValueError(f"{ACTION_SPECS[kind][0]}次数必须为整数")
            slot = entry.get("slot", 1)
            if isinstance(slot, bool) or slot not in SLOT_NAMES:
                raise ValueError("角色位须为一号位、二号位或三号位")
            modules.append({"id": module_id, "kind": kind, "value": int(value) if value.is_integer() else value,
                            "interval": interval, "slot": int(slot)})
        for slot in SLOT_NAMES:
            if sum(m["kind"] == "idle_attack" and m["slot"] == slot for m in modules) > 1:
                raise ValueError("每个角色位只能添加一个空闲普攻模块")
        if not modules and raw.get("version", 1) == 1:
            modules = default_store()["presets"][0]["modules"]
        if not modules or len(modules) > 100:
            raise ValueError("每个预设须有 1 到 100 个模块")
        times = source.get("slot_times", {})
        if not isinstance(times, dict):
            raise ValueError("驻场时间格式错误")
        checked_times = {}
        for slot in SLOT_NAMES:
            duration = float(times.get(str(slot), 5))
            if not math.isfinite(duration) or not 0.2 <= duration <= 120:
                raise ValueError("驻场时间须在 0.2 到 120 秒之间")
            checked_times[str(slot)] = duration
        presets.append({"id": preset_id, "name": name, "slot_times": checked_times,
                        "modules": sorted(modules, key=lambda m: m["slot"])})
    if not 1 <= len(presets) <= 30:
        raise ValueError("预设数量须为 1 到 30")
    active = str(raw.get("active", ""))
    if active not in seen_presets:
        raise ValueError("当前战斗预设不存在")
    mode_source = raw.get("modes", {mode: active for mode in COMBAT_MODES})
    if not isinstance(mode_source, dict):
        raise ValueError("模式预设配置格式错误")
    modes = {}
    for mode in COMBAT_MODES:
        selected = str(mode_source.get(mode, active))
        if selected not in seen_presets:
            raise ValueError(f"{COMBAT_MODES[mode]}的战斗预设不存在")
        modes[mode] = selected
    return {"version": 3, "active": active, "modes": modes, "presets": presets}


def load_store(path: Path) -> dict:
    if not path.exists():
        return default_store()
    store = validate_store(json.loads(path.read_text(encoding="utf-8")))
    defaults = default_store()["presets"][0]
    previous_modules = [m for m in defaults["modules"] if m["slot"] == 1]
    def signature(modules):
        return [{k: v for k, v in m.items() if k != "id"} for m in modules]
    for preset in store["presets"]:
        # Only upgrade the untouched built-in axis. Customized axes stay intact.
        if (preset["id"] == "default" and preset["name"] == "默认战斗轴"
                and preset["slot_times"] == {"1": 5, "2": 5, "3": 5}
                and signature(preset["modules"]) == signature(previous_modules)):
            preset["modules"].extend(deepcopy(defaults["modules"][len(previous_modules):]))
            preset["slot_times"]["3"] = defaults["slot_times"]["3"]
        elif preset["id"] == "default" and preset["name"] == "默认战斗轴" and preset["slot_times"] == defaults["slot_times"]:
            previous_healing = deepcopy(defaults["modules"][:-1])
            previous_healing[len(previous_modules)]["value"] = 2
            if signature(preset["modules"]) == signature(previous_healing):
                preset["modules"][len(previous_modules)]["value"] = .35
                preset["modules"].append(deepcopy(defaults["modules"][-1]))
    return store


def save_store(path: Path, store: dict) -> None:
    checked = validate_store(store)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def active_modules(store: dict, mode: str | None = None) -> list[dict]:
    checked = validate_store(store)
    selected = checked["active"] if mode is None else checked["modes"][mode]
    return deepcopy(next(p["modules"] for p in checked["presets"] if p["id"] == selected))


class RotationClock:
    """One visit per populated column; idle attacks never overlap another action."""

    def __init__(self, modules, started, attack_interval=0.15, slot_times=None, background_idle=False):
        self.modules = deepcopy(modules)
        if not modules:
            raise ValueError("战斗轴不能为空")
        self.columns = {slot: [m for m in self.modules if m.get("slot", 1) == slot]
                        for slot in SLOT_NAMES}
        self.slots = [slot for slot in SLOT_NAMES if self.columns[slot]]
        self.times = slot_times or {str(slot): 5 for slot in SLOT_NAMES}
        self.slot_index = 0
        self.slot = self.slots[0]
        self.visit_deadline = started + float(self.times[str(self.slot)])
        self.needs_select = True
        self.cursor = 0
        self.active = None
        self.last_run = {m["id"]: float("-inf") for m in self.modules}
        self.attack_interval = attack_interval
        self.next_attack = started
        self.remaining = 0
        self.idle_count = 0
        self.background_idle = background_idle

    def _next_slot(self, now):
        self.slot_index = (self.slot_index + 1) % len(self.slots)
        self.slot = self.slots[self.slot_index]
        self.visit_deadline = now + float(self.times[str(self.slot)])
        self.needs_select = True
        self.cursor = 0
        self.active = None
        self.idle_count = 0
        self.next_attack = now

    def has_following_wait(self, now):
        column = self.columns[self.slot]
        if self.cursor >= len(column):
            return False
        item = column[self.cursor]
        return item["kind"] == "wait" and now - self.last_run[item["id"]] >= float(item["interval"])

    def next_action(self, now):
        if now >= self.visit_deadline:
            self._next_slot(now)
        column = self.columns[self.slot]
        if self.needs_select:
            self.needs_select = False
            return {"kind": "select_slot", "module": column[0]}
        if self.active:
            item, deadline = self.active
            kind = item["kind"]
            if kind == "wait" and now < deadline:
                return None
            if kind == "attack_seconds" and now < deadline:
                if now < self.next_attack:
                    return None
                self.next_attack = now + self.attack_interval
                return {"kind": "left_click", "module": item}
            if kind in {"attack_count", "jump_attack", "heavy_count"} and self.remaining > 0:
                if now < self.next_attack:
                    return None
                self.remaining -= 1
                self.next_attack = now + self.attack_interval
                return {"kind": "hold_left" if kind == "heavy_count" else "left_click", "module": item}
            self.active = None
        while self.cursor < len(column):
            item = column[self.cursor]
            self.cursor += 1
            kind = item["kind"]
            if kind == "idle_attack":
                continue
            if now - self.last_run[item["id"]] < float(item["interval"]):
                continue
            self.last_run[item["id"]] = now
            if kind in {"attack_count", "jump_attack", "attack_seconds", "heavy_count", "wait"}:
                self.active = (item, min(self.visit_deadline, now + float(item["value"])))
                self.remaining = int(item["value"])
                self.next_attack = now + self.attack_interval
                if kind == "wait":
                    return {"kind": "wait", "module": item}
                if kind == "jump_attack":
                    return {"kind": "jump", "module": item}
                self.remaining -= 1
                return {"kind": "hold_left" if kind == "heavy_count" else "left_click", "module": item}
            return {"kind": kind, "module": item}
        idle = next((m for m in column if m["kind"] == "idle_attack"), None)
        if idle is not None and self.background_idle:
            return {"kind": "idle_attack", "module": idle}
        if idle is not None and now >= self.next_attack:
            self.next_attack = now + self.attack_interval
            if self.idle_count >= int(idle["value"]):
                self.idle_count = 0
                return {"kind": "hold_left", "module": idle}
            self.idle_count += 1
            return {"kind": "left_click", "module": idle}
        return None


class BattleMonitor:
    """One screenshot check at a time, independent of the input scheduler."""

    def __init__(self, inspect, initial, stop_event):
        self.inspect = inspect
        self.stop_event = stop_event
        self.condition = threading.Condition()
        self.result = (initial,)
        self.requested = False
        self.busy = False
        self.enabled = True
        self.closed = False
        self.error = None
        self.thread = threading.Thread(target=self._run, name="wwbs-battle-monitor", daemon=True)
        self.thread.start()

    def poll(self):
        with self.condition:
            result, self.result = self.result, None
            return result

    def request(self):
        with self.condition:
            if self.enabled and not self.closed and not self.busy and self.result is None:
                self.requested = True
                self.condition.notify_all()

    def pause(self):
        with self.condition:
            self.enabled = False
            self.requested = False
            self.result = None
            while self.busy:
                self.condition.wait()

    def resume(self):
        with self.condition:
            self.enabled = True

    def close(self):
        with self.condition:
            self.closed = True
            self.requested = False
            self.condition.notify_all()
        self.thread.join()

    def _run(self):
        try:
            while True:
                with self.condition:
                    while not self.closed and not self.stop_event.is_set() and not self.requested:
                        self.condition.wait(.05)
                    if self.closed or self.stop_event.is_set():
                        return
                    self.requested = False
                    self.busy = True
                try:
                    result = self.inspect()
                    with self.condition:
                        if self.enabled and not self.closed:
                            self.result = (result,)
                finally:
                    with self.condition:
                        self.busy = False
                        self.condition.notify_all()
        except Exception as exc:
            self.error = exc
            self.stop_event.set()


class IdleAttackWorker:
    """Steady idle clicks independent of screenshot latency, with a pause barrier."""

    def __init__(self, controller, stop_event, input_lock, *, attack_interval=0.15,
                 heavy_hold_ms=800, on_error=None):
        self.controller = controller
        self.stop_event = stop_event
        self.input_lock = input_lock
        self.interval = attack_interval
        self.heavy_hold_ms = heavy_hold_ms
        self.on_error = on_error or (lambda exc: None)
        self.condition = threading.Condition()
        self.state = None
        self.identity = None
        self.count = 0
        self.next_click = 0.0
        self.closed = False
        self.error = None
        self.thread = threading.Thread(target=self._run, name="wwbs-idle-attack", daemon=True)
        self.thread.start()

    def arm(self, module, deadline):
        with self.condition:
            identity = (module["id"], module.get("slot", 1))
            if identity != self.identity:
                self.identity = identity
                self.count = 0
            if self.state is None:
                self.next_click = time.monotonic()
            self.state = (int(module["value"]), deadline)
            self.condition.notify_all()

    def pause(self):
        with self.condition:
            self.state = None
            self.condition.notify_all()
        # A long press must finish and release before a skill or switch begins.
        with self.input_lock:
            pass

    def close(self):
        self.pause()
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.thread.join(timeout=2)

    def _run(self):
        try:
            while True:
                with self.condition:
                    if self.closed or self.stop_event.is_set():
                        return
                    now = time.monotonic()
                    if self.state is not None and now >= self.state[1]:
                        self.state = None
                    if self.state is None:
                        self.condition.wait(0.05)
                        continue
                    delay = self.next_click - now
                    if delay > 0:
                        self.condition.wait(min(delay, max(0, self.state[1] - now), 0.05))
                        continue
                with self.input_lock:
                    with self.condition:
                        now = time.monotonic()
                        if self.closed or self.stop_event.is_set():
                            return
                        if self.state is None or now >= self.state[1]:
                            continue
                        heavy_every, deadline = self.state
                        heavy = self.count >= heavy_every
                        hold_ms = min(self.heavy_hold_ms, max(1, int((deadline-now)*1000)))
                    if heavy:
                        self.controller.hold_left_button(hold_ms)
                        self.count = 0
                        # Holding is itself an attack; resume without another full gap.
                        next_click = time.monotonic() + 0.025
                    else:
                        self.controller.left_click()
                        self.count += 1
                        # Target a start-to-start rhythm, never catch up with bursts.
                        next_click = max(now + self.interval, time.monotonic())
                    with self.condition:
                        self.next_click = next_click
        except Exception as exc:
            self.error = exc
            self.stop_event.set()
            self.on_error(exc)
