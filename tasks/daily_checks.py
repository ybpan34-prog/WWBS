"""Bounded fresh-frame confirmation shared by daily navigation steps."""
from pathlib import Path
import time


class DailyStepChecks:
    def __init__(self, runner, screenshot=None):
        self.runner = runner
        self.screenshot = screenshot or Path(__file__).resolve().parent.parent/'_runtime_screenshot.png'

    def transition(self, label, destination, action=None, *, timeout=15, require_action=False, recovery=None):
        deadline = time.monotonic()+timeout
        frames = attempts = ready = recoveries = 0
        next_click = 0.
        while time.monotonic() < deadline and not self.runner.stop_event.is_set():
            self.runner._capture_for_matching(self.screenshot)
            if self.runner.stop_event.is_set():
                return False
            frames += 1
            satisfied = (not require_action or attempts > 0) and bool(destination(self.screenshot))
            ready = ready+1 if satisfied else 0
            if ready >= 2:
                self.runner.log(f'    已复核「{label}」（{frames}张截图，操作{attempts}次），继续。')
                return True
            if not satisfied and time.monotonic() >= next_click:
                if action is not None and attempts < 3 and action(self.screenshot):
                    attempts += 1
                    next_click = time.monotonic()+1.8
                    self.runner.log(f'    「{label}」已操作，等待目标状态复核（第{attempts}次）。')
                elif recovery is not None and recoveries < 3 and recovery(self.screenshot):
                    recoveries += 1
                    next_click = time.monotonic()+1.8
            self.runner._sleep_interruptible(.2)
        if self.runner.stop_event.is_set():
            return False
        raise RuntimeError(f'「{label}」已复核{frames}张截图、操作{attempts}次，仍未确认目标状态；未继续后续步骤。')
