"""4C 战斗、轮换、吸收与重开流程。"""

import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from combat_rotation import BattleMonitor, IdleAttackWorker, RotationClock, SLOT_NAMES
from tasks.models import Step


APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"


class Combat4CTask:
    def _run_4c_combat(self, step: Step) -> None:
        required = (
            "press_keys",
            "press_key",
            "press_binding",
            "left_click",
            "hold_left_button",
            "middle_click",
            "wheel_at",
            "move_mouse_relative",
            "release_keys",
        )
        if any(not hasattr(self.controller, name) for name in required):
            raise RuntimeError("4C刷取目前只支持 PC 客户端窗口。")
        skill_key = self.controller.normalize_input_binding(self.combat_skill_key)
        ultimate_key = self.controller.normalize_input_binding(self.combat_ultimate_key)
        cycle_count = max(1, int(self.max_cycles or 1))
        if self.dry_run:
            self.log(
                f"    干运行：计划执行 {cycle_count} 轮；每轮开打先按鼠标中键锁定敌人，"
                f"然后按4C预设依次执行 {len(self.rotation_presets.get('combat_4c', self.rotation_modules))} 个模块；"
                f"技能键 {skill_key}，大招键 {ultimate_key}。"
            )
            return

        self.log(
            f"    4C刷取已开始：共 {cycle_count} 轮，当前技能键位 {skill_key}，"
            f"大招键位 {ultimate_key}。"
        )
        try:
            if self.boss_challenge is not None and not self.boss_challenge.enter(self):
                return
            for cycle_index in range(1, cycle_count + 1):
                if self.stop_event.is_set():
                    self.log("    收到停止信号，4C刷取已停止。")
                    return
                self.log(f"    === 第 {cycle_index}/{cycle_count} 轮 ===")
                self._run_4c_battle(step, skill_key, ultimate_key, cycle_index)
                if self.stop_event.is_set():
                    return
                self._collect_4c_reward(cycle_index)
                if self.stop_event.is_set():
                    return
                if cycle_index >= cycle_count:
                    self.log(f"    已完成 {cycle_count} 轮战斗与吸收，停止4C刷取。")
                    return
                self._restart_4c_challenge(cycle_index + 1)
                if self.boss_challenge is not None:
                    self.boss_challenge.wait_for_battle(self)
        finally:
            try:
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3", "4"))
            except Exception as exc:
                self.log(f"    释放战斗按键时遇到问题: {exc}")

    def _run_4c_battle(self, step: Step, skill_key: str, ultimate_key: str, cycle_index: int) -> None:
        started = time.monotonic()
        deadline = started + max(30.0, step.timeout)
        modules = self.rotation_presets.get("combat_4c", self.rotation_modules)
        self._rotation_slot = None
        self._rotation_battle_finished = False
        self._rotation_end_check = self._4c_switch_end_present
        self._combat_animation_until = 0.
        self._combat_input_cancel.clear()
        self._rotation_continuous_started = False
        last_header_check = 0.0
        boss_header_seen = False
        screenshot = APP_DIR / "_runtime_screenshot.png"
        self.log(f"    第{cycle_index}轮：鼠标中键锁定敌人。")
        self.controller.middle_click()
        attack_enabled = threading.Event()
        attack_lock = threading.Lock()
        idle_worker = IdleAttackWorker(self.controller, self.stop_event, attack_lock,
                                       attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                                       heavy_hold_ms=self.HEAVY_ATTACK_HOLD_MS,
                                       on_error=lambda exc: self.log(f"    空闲普攻失败：{exc}"))
        self._rotation_idle_worker = idle_worker
        monitor = None
        try:
            inspect = lambda: self._inspect_4c_battle_state(screenshot, cycle_index, 0, log_result=False)
            initial = inspect()
            rotation = RotationClock(modules, time.monotonic(), self.MAIN_ATTACK_CLICK_INTERVAL,
                                     self.rotation_times.get("combat_4c"), background_idle=True,
                                     slot_order=self.rotation_orders.get("combat_4c"))
            def stop_on_prompt(result):
                if result[1]:
                    self._rotation_battle_finished = True
                    self._combat_input_cancel.set()
                    idle_worker.close()
                    attack_enabled.clear()
                    self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3"))
                    self.log(f"    识别到{result[1]}，立即停止战斗输入，进入吸收。")
            monitor = BattleMonitor(inspect, initial, self.stop_event, on_result=stop_on_prompt)
            while time.monotonic() < deadline:
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                checked = monitor.poll()
                if checked is not None:
                    header_present, reward_hint = checked[0]
                    last_header_check = time.monotonic()
                    if reward_hint:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        self.controller.release_keys()
                        hint = reward_hint if isinstance(reward_hint, str) else "领取奖励"
                        self.log(f"    第{cycle_index}轮：出现{hint}提示，战斗已结束，进入声骸吸收流程。")
                        return
                    elif header_present:
                        boss_header_seen = True
                    elif header_present is None or time.monotonic() < self._combat_animation_until:
                        # Ultimate cutscenes hide the HUD. Keep the current axis
                        # and idle attacks running; this frame is not a defeat.
                        pass
                    elif boss_header_seen:
                        idle_worker.pause()
                        monitor.pause()
                        attack_enabled.clear()
                        with attack_lock:
                            pass
                        missing_header_checks = 1
                        self.controller.release_keys()
                        self.log("    战斗监测发现首领名字与血条疑似消失，暂停攻击并快速复核。")
                        while missing_header_checks < self.EMPTY_HEALTH_CONFIRMATIONS:
                            self._sleep_interruptible(self.EMPTY_HEALTH_CONFIRMATION_INTERVAL)
                            header_present, reward_hint = self._inspect_4c_battle_state(
                                screenshot,
                                cycle_index,
                                missing_header_checks,
                            )
                            if reward_hint:
                                self.log(f"    第{cycle_index}轮：复核发现结束提示，进入声骸吸收流程。")
                                return
                            if header_present is None or time.monotonic() < self._combat_animation_until:
                                missing_header_checks = 0
                                break
                            if header_present:
                                missing_header_checks = 0
                                break
                            missing_header_checks += 1
                        if missing_header_checks >= self.EMPTY_HEALTH_CONFIRMATIONS:
                            self.controller.release_keys()
                            self.log(
                                f"    第{cycle_index}轮：已确认首领名字与整条血条彻底消失，进入吸收流程。"
                            )
                            return
                        monitor.resume()
                        last_header_check = time.monotonic()
                    elif now - started >= 15.0:
                        raise RuntimeError("没有检测到屏幕顶部的首领名字和血条，已停止4C刷取。请先进入战斗。")
                elif now - last_header_check >= self.BOSS_HEADER_CHECK_INTERVAL:
                    monitor.request()
                action = rotation.next_action(time.monotonic())
                if not self._run_rotation_action(action, rotation, skill_key, ultimate_key,
                                                 attack_enabled, attack_lock):
                    return
                self._sleep_interruptible(0.025)
            raise RuntimeError("单轮4C战斗达到安全时限，已自动停止。")
        finally:
            idle_worker.close()
            self._rotation_end_check = None
            self._rotation_idle_worker = None
            attack_enabled.clear()
            try:
                self.controller.release_keys()
            finally:
                if monitor is not None:
                    monitor.close()
            if monitor is not None and monitor.error is not None:
                raise RuntimeError(f"战斗画面检查失败：{monitor.error}") from monitor.error
            if idle_worker.error is not None:
                raise RuntimeError(f"空闲普攻失败：{idle_worker.error}") from idle_worker.error

    def _inspect_4c_battle_state(
        self, screenshot: Path, cycle_index: int, missing_checks: int, *, log_result: bool = True,
    ) -> tuple[bool | None, bool | str]:
        # Both signals use the same fresh frame; the reward hint is optional.
        inspected_at = time.monotonic()
        header_present = self._inspect_4c_boss_header(
            screenshot, cycle_index, missing_checks, log_result=log_result,
        )
        if self._4c_reward_hint_present(screenshot):
            return header_present, "领取奖励"
        try:
            with Image.open(screenshot) as captured:
                scale = captured.width / 1920.0
            prompt, _name = self._find_4c_absorb_prompt(screenshot, scale, fast=True)
        except (OSError, ValueError):
            prompt = None
        if prompt is not None:
            return header_present, "吸收"
        if not header_present:
            native_check = callable(getattr(type(self.controller), 'active_character_slot', None))
            if (inspected_at < self._combat_animation_until
                    or (native_check and (not self._overworld_hud_ready(screenshot)
                                          or self.controller.active_character_slot(screenshot) is None))):
                return None, False
        return header_present, False

    def _4c_reward_hint_present(self, screenshot: Path) -> bool:
        try:
            with Image.open(screenshot) as source:
                width, height = source.size
        except (OSError, ValueError):
            return False
        scale = height / 1080.0
        match = self._find_daily_template(
            str(TEMPLATES_DIR / "4c" / "claim_reward_hint.png"), threshold=0.86,
            region=(0, round(height * 0.12), round(width * 0.20), round(height * 0.65)),
            scales=[scale, scale * 0.96, scale * 1.04], screenshot=screenshot,
        )
        return match is not None

    def _inspect_4c_boss_header(
        self,
        screenshot: Path,
        cycle_index: int,
        missing_checks: int,
        *,
        log_result: bool = True,
    ) -> bool:
        """Capture the boss header and report whether its name or full track remains."""
        self._capture_for_matching(screenshot)
        health_ratio = self._boss_health_ratio(screenshot)
        name_ratio = self._boss_name_ratio(screenshot)
        bar_track_score = self._boss_bar_track_score(screenshot)
        header_present = name_ratio >= 0.015 or bar_track_score >= 0.18
        confirmation = 0 if header_present else missing_checks + 1
        if log_result:
            self.log(
                f"    第{cycle_index}轮快速复核：血量色彩 {health_ratio:.3f}，名字 {name_ratio:.3f}，"
                f"血条轨道 {bar_track_score:.3f}"
                f"（完整消失确认 {confirmation}/{self.EMPTY_HEALTH_CONFIRMATIONS}）。"
            )
        return header_present

    def _run_4c_continuous_attack(
        self,
        attack_enabled: threading.Event,
        attack_finished: threading.Event,
        attack_lock: threading.Lock,
        heavy_every: int | None = None,
    ) -> None:
        """Attack on its own clock so screenshots and movement never form click bursts."""
        attack_count = 0
        while not attack_finished.is_set() and not self.stop_event.is_set():
            if not attack_enabled.wait(timeout=0.05):
                continue
            if attack_finished.is_set() or self.stop_event.is_set():
                return
            try:
                with attack_lock:
                    if attack_enabled.is_set():
                        if attack_count >= (heavy_every or self.HEAVY_ATTACK_EVERY):
                            self.controller.hold_left_button(self.HEAVY_ATTACK_HOLD_MS)
                            attack_count = 0
                        else:
                            self.controller.left_click()
                            attack_count += 1
            except Exception as exc:
                self.log(f"    持续普攻失败：{exc}")
                self.stop_event.set()
                return
            attack_finished.wait(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _rotation_first_slot(self, modules: list[dict], mode: str) -> int:
        occupied = {item.get("slot", 1) for item in modules}
        return next(slot for slot in self.rotation_orders.get(mode, [1, 2, 3]) if slot in occupied)

    def _4c_switch_end_present(self, screenshot: Path) -> bool:
        if self._4c_reward_hint_present(screenshot):
            return True
        with Image.open(screenshot) as image:
            scale = image.width / 1920
        return self._find_4c_absorb_prompt(screenshot, scale, fast=True)[0] is not None

    def _read_rotation_slot(self, *, check_end: bool = True) -> int | None:
        screenshot = APP_DIR / '_role_screenshot.png'
        self._capture_for_matching(screenshot)
        observed = self.controller.active_character_slot(screenshot)
        # The first frame checks settlement. On the second, inspect it again only
        # when the HUD disappeared; a valid portrait does not need another full scan.
        if ((check_end or observed is None) and self._rotation_end_check is not None
                and self._rotation_end_check(screenshot)):
            self._rotation_battle_finished = True
            self.log("    切人确认时发现战斗结束，停止切人并进入任务收尾。")
            return None
        return observed

    def _select_rotation_slot(self, slot: int, *, verify: bool = False) -> bool:
        if self.stop_event.is_set():
            return False
        if self._rotation_battle_finished:
            return False
        native_check = callable(getattr(type(self.controller), 'active_character_slot', None))
        if native_check and (verify or self._rotation_slot != slot):
            worker = getattr(self, '_rotation_idle_worker', None)
            owned = not isinstance(worker, IdleAttackWorker)
            if owned:
                worker = IdleAttackWorker(self.controller, self.stop_event, threading.Lock(),
                    attack_interval=self.MAIN_ATTACK_CLICK_INTERVAL,
                    on_error=lambda exc: self.log(f'    切人确认时普攻失败：{exc}'))
            try:
                return self._confirm_rotation_slot(slot, worker)
            finally:
                if owned:
                    worker.close()
                else:
                    worker.pause()
        if self._rotation_slot != slot:
            self.controller.press_key(str(slot), 65)
            self._rotation_slot = slot
        return not self.stop_event.is_set()

    def _confirm_rotation_slot(self, slot, worker):
        deadline = time.monotonic()+6.0
        attempt, observed = 0, None
        while time.monotonic() < deadline and not self.stop_event.is_set():
            observed = self._read_rotation_slot()
            if self._rotation_battle_finished or self.stop_event.is_set():
                return False
            if observed is None and time.monotonic() < self._combat_animation_until:
                self._sleep_interruptible(.08)
                continue
            if observed == slot:
                self._sleep_interruptible(.025)
                if self.stop_event.is_set():
                    return False
                if (self._read_rotation_slot(check_end=False) == slot and not self._rotation_battle_finished
                        and not self.stop_event.is_set()):
                    self._rotation_slot = slot
                    self.log(f"    已确认{SLOT_NAMES[slot]}上场，开始执行该角色模块。")
                    return True
                if self._rotation_battle_finished:
                    return False
            attempt += 1
            with worker.input_lock:
                if self.stop_event.is_set() or self._rotation_battle_finished:
                    return False
                self.controller.release_keys(("W", "A", "S", "D", "SPACE", "1", "2", "3"))
                self.controller.press_key(str(slot), 65)
            worker.arm_switch_confirmation(deadline)
            self.log(f"    请求切到{SLOT_NAMES[slot]}（第{attempt}次），边普攻边确认头像栏。")
            self._sleep_interruptible(.08)
        if self.stop_event.is_set():
            return False
        current = SLOT_NAMES.get(observed, '未识别')
        raise RuntimeError(f"未能确认切到{SLOT_NAMES[slot]}，最后识别为{current}。已停止，不会跳过此角色继续切人。")

    def _run_rotation_action(self, action: dict | None, rotation: RotationClock,
                             skill_key: str, ultimate_key: str,
                             attack_enabled: threading.Event, attack_lock: threading.Lock,
                             *, daily: bool = False, task_seen: bool = True,
                             screenshot: Path | None = None) -> bool:
        if self._rotation_battle_finished or self.stop_event.is_set():
            return False
        if action is None:
            return not self.stop_event.is_set()
        kind, item = action["kind"], action["module"]
        idle_worker = getattr(self, "_rotation_idle_worker", None)
        if kind == "idle_attack":
            if idle_worker is not None and self._rotation_slot == item.get("slot", 1):
                idle_worker.arm(item, rotation.visit_deadline)
            return not self.stop_event.is_set()
        if idle_worker is not None:
            idle_worker.pause()
        attack_enabled.clear()
        if not self._select_rotation_slot(item.get("slot", 1), verify=kind == "select_slot"):
            return False
        if kind == "select_slot":
            rotation.start_visit(time.monotonic())
            return True
        if kind == "wait":
            return True
        if time.monotonic() >= rotation.visit_deadline:
            return True
        if kind == "left_click":
            self.controller.left_click()
        elif kind == "hold_left":
            remaining_ms = max(1, round((rotation.visit_deadline - time.monotonic()) * 1000))
            duration = min(self.HEAVY_ATTACK_HOLD_MS, remaining_ms)
            if callable(getattr(type(self.controller), 'hold_left_button_cancelable', None)):
                self.controller.hold_left_button_cancelable(duration, self._combat_input_cancel)
            else:
                self.controller.hold_left_button(duration)
        elif kind == "jump":
            self.controller.press_key("SPACE", 50)
        elif kind in {"skill", "ultimate", "echo"}:
            if self.stop_event.is_set():
                return False
            rotation.last_run[item["id"]] = time.monotonic()
            explicit_wait = rotation.has_following_wait(time.monotonic())
            idle_module = next((module for module in rotation.columns[rotation.slot]
                                if module['kind'] == 'idle_attack'), None)
            resume_idle = (idle_worker is not None and rotation.background_idle
                           and idle_module is not None and not explicit_wait)
            if kind == "skill":
                self.controller.press_binding(skill_key, 65)
                if not (explicit_wait or resume_idle):
                    self._sleep_interruptible(min(0.20, max(0, rotation.visit_deadline - time.monotonic())))
            elif kind == "ultimate":
                self._cast_timed_ultimate(ultimate_key, attack_enabled, attack_lock, resume_attacks=False,
                                         settle_delay=0 if explicit_wait or resume_idle else min(0.8, max(0, rotation.visit_deadline - time.monotonic())))
            else:
                self.controller.press_key("Q", 120)
                if not (explicit_wait or resume_idle):
                    self._sleep_interruptible(min(self.ECHO_ACTION_SETTLE_DELAY,
                                                  max(0, rotation.visit_deadline - time.monotonic())))
            # Resume only after the cast key is released. Due-module inspection
            # then runs alongside the idle worker; actual actions pause it again.
            if resume_idle and not self.stop_event.is_set() and not self._rotation_battle_finished:
                # Preserve the skill-to-skill cadence, but represent it in the
                # scheduler so idle clicks and ending checks remain responsive.
                delay = {'skill': .2, 'ultimate': .8, 'echo': self.ECHO_ACTION_SETTLE_DELAY}[kind]
                rotation.defer_cast_followup(time.monotonic(), delay)
                idle_worker.arm(idle_module, rotation.visit_deadline)
        elif kind == "approach":
            duration = min(float(item["value"]), max(0, rotation.visit_deadline - time.monotonic()))
            if callable(getattr(type(self.controller), 'press_keys_cancelable', None)):
                self.controller.press_keys_cancelable(("W",), max(1, round(duration*1000)), self._combat_input_cancel)
            else:
                self.controller.press_keys(("W",), max(1, round(duration * 1000)))
        return not self.stop_event.is_set()

    def _perform_4c_main_attack(self) -> None:
        """Keep a steady main-character attack rhythm matching the healer clicks."""
        self.controller.left_click()
        self._sleep_interruptible(self.MAIN_ATTACK_CLICK_INTERVAL)

    def _cast_timed_ultimate(
        self,
        ultimate_key: str,
        attack_enabled: threading.Event,
        attack_lock: threading.Lock,
        *, resume_attacks: bool = True, settle_delay: float = 0.8,
    ) -> None:
        """Give the ultimate input a quiet window without competing attack clicks."""
        attack_enabled.clear()
        with attack_lock:
            pass
        try:
            if self.stop_event.is_set():
                return
            self._combat_animation_until = time.monotonic()+5.
            self.controller.press_binding(ultimate_key, 120)
            self._sleep_interruptible(settle_delay)
        finally:
            if resume_attacks and not self.stop_event.is_set():
                attack_enabled.set()

    def _perform_4c_heal_rotation(self, skill_key: str) -> bool:
        """Third-slot heal combo with short attack spacing and a clear return delay."""
        if self.stop_event.is_set():
            return False
        self.controller.press_key("3", 65)
        self._sleep_interruptible(self.HEAL_SWITCH_SETTLE_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_binding(skill_key, 65)
        self._sleep_interruptible(0.08)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("SPACE", 50)
        self._sleep_interruptible(0.035)
        for click_index in range(3):
            if self.stop_event.is_set():
                return False
            self.controller.left_click()
            if click_index < 2:
                self._sleep_interruptible(self.HEAL_ATTACK_CLICK_INTERVAL)
        self._sleep_interruptible(self.HEAL_RETURN_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("SPACE", 50)
        self._sleep_interruptible(0.035)
        for click_index in range(3):
            if self.stop_event.is_set():
                return False
            self.controller.left_click()
            if click_index < 2:
                self._sleep_interruptible(self.HEAL_ATTACK_CLICK_INTERVAL)
        if self.stop_event.is_set():
            return False
        self._sleep_interruptible(self.HEAL_ATTACK_TO_Q_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("Q", 120)
        self._sleep_interruptible(self.HEAL_Q_TO_RETURN_DELAY)
        if self.stop_event.is_set():
            return False
        self.controller.press_key("1", 65)
        self._sleep_interruptible(0.22)
        return not self.stop_event.is_set()

    def _collect_4c_reward(self, cycle_index: int) -> None:
        screenshot = APP_DIR / "_runtime_screenshot.png"
        deadline = time.monotonic() + self.REWARD_SEARCH_TIMEOUT
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            self._capture_for_matching(screenshot)
            with Image.open(screenshot) as captured:
                scale = captured.width / 1920.0
            prompt, prompt_name = self._find_4c_absorb_prompt(screenshot, scale)
            if prompt is not None:
                self.log(
                    f"    第{cycle_index}轮：发现吸收提示 {prompt_name}，"
                    f"相似度 {prompt.score:.3f}，立即按 F。"
                )
                self.controller.release_keys()
                self.controller.press_key("F", 100)
                self._sleep_interruptible(2.8)
                return
            if self.stop_event.is_set():
                return
            self.controller.press_keys(("W",), 400)
            self.log(f"    第{cycle_index}轮：未出现吸收提示，向前移动一小段后重新检查。")
            self._sleep_interruptible(0.10)
        raise RuntimeError("击败首领后向前搜索仍未找到“F / 吸收”提示，已停止循环。")

    def _approach_4c_gold_target(self, offset_x: float, screen_width: int) -> str:
        """Approach a visible echo without violating the right-only camera search."""
        centre_tolerance = screen_width * 0.045
        if offset_x < -centre_tolerance:
            # Keep the camera direction stable and strafe toward a visible target;
            # a full rightward wrap used to throw left-side echoes out of view.
            self.controller.press_keys(("W", "A"), 400)
            return "目标在左侧，向左前方靠近"
        if offset_x > centre_tolerance:
            turn = int(max(110, min(360, offset_x * 0.40)))
            self.controller.move_mouse_relative(turn, 0)
            self.controller.press_keys(("W",), 360)
            return "目标在右侧，向右微调并靠近"
        self.controller.press_keys(("W",), 500)
        return "目标已在中央，直线靠近"

    def _find_4c_absorb_prompt(self, screenshot: Path, scale: float, *, fast: bool = False):
        best = None
        best_name = ""
        with Image.open(screenshot) as captured:
            width, height = captured.size
        prompt_region = (
            round(width * 0.42),
            round(height * 0.22),
            round(width * 0.96),
            round(height * 0.86),
        )
        scales = []
        candidates = ((scale, scale * 0.97, scale * 1.03) if fast else
                      (scale, scale * 0.94, scale * 0.97, scale * 1.03, scale * 1.06, scale * 0.88, scale * 1.12))
        for candidate in candidates:
            if candidate > 0.2 and all(abs(candidate - known) > 0.01 for known in scales):
                scales.append(candidate)
        for template_name in self.ABSORB_PROMPT_TEMPLATES:
            text_crop = self.ABSORB_TEXT_CROPS[template_name]
            for candidate_scale in scales:
                try:
                    match = self.matcher.find_fast(
                        screenshot,
                        template_name,
                        threshold=0.80,
                        scale=candidate_scale,
                        region=prompt_region,
                        template_crop=text_crop,
                    )
                except Exception:
                    continue
                if best is None or match.score > best.score:
                    best = match
                    best_name = template_name
                if fast or match.score >= 0.90:
                    return match, template_name
        return best, best_name

    def _restart_4c_challenge(self, next_cycle: int) -> None:
        self.log(f"    吸收完成，按 Esc 并准备第 {next_cycle} 轮。")
        self.controller.press_key("ESC", 70)
        self._sleep_interruptible(0.85)
        probe = Step(
            action="tap_image",
            template="restart_challenge.png",
            threshold=0.75,
            timeout=10.0,
            offset_x=0,
            offset_y=0,
        )
        x, y, score = self._find_image(probe)
        self.log(f"    找到重新挑战按钮：({x}, {y})，相似度 {score:.3f}。")
        self.controller.tap(x, y)
        self._sleep_interruptible(3.0)

    @staticmethod
    def _boss_health_ratio(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        expected_game_height = round(width * 9 / 16)
        titlebar_height = max(0, height - expected_game_height)
        game_height = height - titlebar_height
        top = max(0, titlebar_height + round(game_height * 0.035))
        bottom = min(height, titlebar_height + round(game_height * 0.070))
        left = max(0, round(width * 0.34))
        right = min(width, round(width * 0.66))
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        red = region[:, :, 0].astype(np.float32)
        green = region[:, :, 1].astype(np.float32)
        blue = region[:, :, 2].astype(np.float32)
        colored_health = (
            (red > 145)
            & (red > green * 1.12)
            & (red > blue * 1.22)
            & ((green > 55) | (red > 190))
        )
        return float(colored_health.mean())

    @staticmethod
    def _boss_name_ratio(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        titlebar_height = max(0, height - round(width * 9 / 16))
        game_height = height - titlebar_height
        top = titlebar_height + round(game_height * 0.008)
        bottom = titlebar_height + round(game_height * 0.045)
        left, right = round(width * 0.34), round(width * 0.66)
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        high = region.max(axis=2)
        low = region.min(axis=2)
        bright_name = (
            (region[:, :, 0] > 165)
            & (region[:, :, 1] > 155)
            & (region[:, :, 2] > 145)
            & ((high - low) < 95)
        )
        return float(bright_name.mean())

    @staticmethod
    def _boss_bar_track_score(screenshot: Path) -> float:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB")).astype(np.float32)
        height, width = image.shape[:2]
        titlebar_height = max(0, height - round(width * 9 / 16))
        game_height = height - titlebar_height
        top = titlebar_height + round(game_height * 0.035)
        bottom = titlebar_height + round(game_height * 0.075)
        left, right = round(width * 0.34), round(width * 0.66)
        region = image[top:bottom, left:right]
        if region.size == 0:
            return 0.0
        high = region.max(axis=2)
        low = region.min(axis=2)
        neutral_track = ((high - low) < 45) & (high > 85)
        return float(neutral_track.mean(axis=1).max())

    @staticmethod
    def _gold_target_location(screenshot: Path) -> tuple[float, int | None, int | None]:
        with Image.open(screenshot) as source:
            image = np.asarray(source.convert("RGB"))
        height, width = image.shape[:2]
        # High signs are excluded. The lower world view remains searchable because
        # a small echo can sit near the character; lower candidates must be more
        # solid so hollow golden combat rings are rejected.
        top, bottom = round(height * 0.18), round(height * 0.84)
        left, right = round(width * 0.08), round(width * 0.92)
        region = image[top:bottom, left:right]
        red = region[:, :, 0].astype(np.float32)
        green = region[:, :, 1].astype(np.float32)
        blue = region[:, :, 2].astype(np.float32)
        # Absorbable echoes are a saturated deep orange-gold. Pale yellow-white
        # reflections and floor lights must not be treated as navigation targets.
        maximum = np.maximum.reduce((red, green, blue))
        minimum = np.minimum.reduce((red, green, blue))
        saturation = (maximum - minimum) / np.maximum(maximum, 1.0)
        gold = (
            (red > 150)
            & (green > 85)
            & (blue < 145)
            & (saturation >= 0.42)
            & ((red - green) > 18)
            & ((green - blue) > 18)
        )
        if not gold.any():
            return 0.0, None, None

        # Downsample once and lightly join glow fragments. The component filter
        # below accepts small compact echoes, but rejects long rails and streaks.
        sample_step = 3
        sampled = gold[::sample_step, ::sample_step]
        padded = np.pad(sampled, 1, mode="constant")
        expanded = np.logical_or.reduce(
            [
                padded[dy : dy + sampled.shape[0], dx : dx + sampled.shape[1]]
                for dy in range(3)
                for dx in range(3)
            ]
        )

        visited = np.zeros(expanded.shape, dtype=bool)
        best_points: list[tuple[int, int]] = []
        best_score = 0.0
        best_confidence = 0.0
        rows, columns = expanded.shape
        for start_y, start_x in zip(*np.nonzero(expanded & ~visited)):
            if visited[start_y, start_x]:
                continue
            stack = [(int(start_y), int(start_x))]
            visited[start_y, start_x] = True
            points = []
            while stack:
                y, x = stack.pop()
                points.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < rows and 0 <= nx < columns and expanded[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
            ys = [point[0] for point in points]
            xs = [point[1] for point in points]
            component_height = max(ys) - min(ys) + 1
            component_width = max(xs) - min(xs) + 1
            aspect = max(component_width / component_height, component_height / component_width)
            compactness = len(points) / max(1, component_width * component_height)
            component_center_y = (sum(ys) / len(ys)) * sample_step + top
            component_center_x = (sum(xs) / len(xs)) * sample_step
            minimum_compactness = 0.68 if component_center_y > height * 0.60 else 0.43
            valid_shape = aspect <= 2.05 or (
                component_width > component_height and aspect <= 2.80
            )
            # A common false positive is the small gold ring mounted beneath the
            # large yellow MILITECH billboard. Reject a candidate when a broad,
            # dense gold panel occupies the area well above it. Real echoes do not
            # have a billboard-sized gold slab suspended over their position.
            overhead = gold[
                max(0, round(component_center_y - top - height * 0.40)):
                max(1, round(component_center_y - top - height * 0.10)),
                max(0, round(component_center_x - width * 0.16)):
                min(gold.shape[1], round(component_center_x + width * 0.16)),
            ]
            overhead_gold_ratio = float(overhead.mean()) if overhead.size else 0.0
            # Distant echoes form a medium-sized compact cluster. Tiny golden UI
            # marks and large billboards sit outside this range; a very close echo
            # is handled by the F/absorb prompt before colour navigation runs.
            if (
                len(points) < 100
                or len(points) > 1400
                or not valid_shape
                or compactness < minimum_compactness
                or overhead_gold_ratio > 0.055
            ):
                continue
            score = len(points) * compactness
            if score > best_score:
                best_score = score
                best_points = points
                best_confidence = compactness

        if not best_points:
            return float(len(best_points) / max(1, expanded.size)), None, None
        ys = np.fromiter((point[0] for point in best_points), dtype=np.float32)
        xs = np.fromiter((point[1] for point in best_points), dtype=np.float32)
        return (
            float(best_confidence),
            round(float(xs.mean()) * sample_step + left),
            round(float(ys.mean()) * sample_step + top),
        )
