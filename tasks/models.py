"""任务配置与输入客户端。"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Step:
    action: str
    label: str = ""
    template: str = ""
    templates: list[str] = field(default_factory=list)
    template_offsets: dict[str, dict[str, int]] = field(default_factory=dict)
    loop: bool = False
    skip_missing: bool = True
    threshold: float = 0.82
    timeout: float = 8.0
    offset_x: int = 0
    offset_y: int = 0
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None
    duration_ms: int = 300
    seconds: float = 0.8
    text: str = ""


@dataclass
class WeeklyTask:
    name: str
    enabled: bool = True
    weekday: str = "any"
    description: str = ""
    template_group: str = "default"
    steps: list[Step] = field(default_factory=list)


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[WeeklyTask]:
        if not self.path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.path}")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        tasks = []
        for item in raw.get("tasks", []):
            steps = [Step(**step) for step in item.get("steps", [])]
            tasks.append(
                WeeklyTask(
                    name=item["name"],
                    enabled=item.get("enabled", True),
                    weekday=item.get("weekday", "any"),
                    description=item.get("description", ""),
                    template_group=item.get("template_group", "default"),
                    steps=steps,
                )
            )
        return tasks

    def save(self, tasks: list[WeeklyTask]) -> None:
        payload = {
            "version": 1,
            "reset_hint": "鸣潮国服常见周刷新为周一 04:00；如你的服务器不同，请按实际情况改任务 weekday。",
            "tasks": [
                {
                    "name": task.name,
                    "enabled": task.enabled,
                    "weekday": task.weekday,
                    "description": task.description,
                    "template_group": task.template_group,
                    "steps": [step.__dict__ for step in task.steps],
                }
                for task in tasks
            ],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class AdbClient:
    def __init__(self, adb_path: str = "adb", device: str = ""):
        self.adb_path = adb_path.strip() or "adb"
        self.device = device.strip()

    def _base_cmd(self) -> list[str]:
        cmd = [self.adb_path]
        if self.device:
            cmd.extend(["-s", self.device])
        return cmd

    def run(self, args: list[str], timeout: int = 15) -> str:
        result = subprocess.run(
            self._base_cmd() + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise RuntimeError(output or f"ADB 命令失败: {' '.join(args)}")
        return output

    def devices(self) -> str:
        return self.run(["devices"])

    def tap(self, x: int, y: int) -> None:
        self.run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x: int, y: int, x2: int, y2: int, duration_ms: int) -> None:
        self.run(["shell", "input", "swipe", str(x), str(y), str(x2), str(y2), str(duration_ms)])

    def text(self, value: str) -> None:
        escaped = value.replace(" ", "%s")
        self.run(["shell", "input", "text", escaped])

    def screencap(self, target: Path) -> None:
        data = subprocess.run(
            self._base_cmd() + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if data.returncode != 0:
            raise RuntimeError(data.stderr.decode("utf-8", errors="replace") or "截图失败")
        target.write_bytes(data.stdout)
