"""景燃桌宠的集中式语言层。"""

from __future__ import annotations

import random
from dataclasses import dataclass


OWNER_NAME = "漂泊者"
OWNER_ADDRESS_PROBABILITY = 0.36

EVENT_LINES: dict[str, tuple[str, ...]] = {
    "task_start": (
        "阴阳未判，前路未明。无妨，我替你探路。",
        "灯已点起。漂泊者，余下的路交给我。",
    ),
    "task_complete": (
        "此行已毕，祸福皆定。你可以歇一会儿了。",
        "路已经走通，结果也收好了。",
    ),
    "check_start": (
        "稍候，我循着灯火找一找游戏窗口。",
        "先辨清门户，再动身也不迟。",
    ),
    "check_success": (
        "找到了。此门可行。",
        "窗口与画面都对得上，可以启程。",
    ),
    "check_failure": (
        "门扉未开。先确认游戏已经启动并显示在桌面上。",
        "灯火没有照见游戏窗口。打开游戏后，再唤我一次。",
    ),
    "diagnose_start": (
        "我来查看权限、窗口、比例和当前画面。真相总会留下痕迹。",
        "别急，容我循迹查明是哪一环出了偏差。",
    ),
    "diagnose_error": (
        "症结已明：{detail}\n完整线索已经写入日志。",
        "问题在这里：{detail}\n先依照日志处理，再走一次。",
    ),
    "diagnose_warning": (
        "此处尚有隐患：{detail}\n先处理会更稳妥。",
        "路能走，但这一点不可忽视：{detail}\n详情已记在日志里。",
    ),
    "diagnose_ok": (
        "诸项无碍。灯火所照之处，没有发现异常。",
        "检查完毕，可以放心启程。",
    ),
    "stop_requested": (
        "知道了，我会在此收住脚步。",
        "止步即可。剩余流程不会继续。",
    ),
    "mouse_move_failed": (
        "鼠标未能移动。请退出程序，再右键快捷方式，以管理员身份运行。",
        "权限拦住了去路。请用管理员身份重新打开程序。",
    ),
}

IDLE_LINES = (
    "行于阴阳未判之处，踏遍祸福未卜之途，借阴路而行，自也向死地而生。",
    "灯火尚明，不必急着赶路。",
    "祸福未卜时，先看清脚下。",
    "漂泊者，若是累了，就在灯下停一会儿。",
    "风声有异……无妨，只是远路传来的回响。",
    "有些路看似断绝，不过是入口藏得更深。",
    "今日的灯火很安静，正适合慢慢想事情。",
)

IDLE_ACTIONS = ("waving", "jumping", "review", "waiting")
_idle_action_bag: list[str] = []


@dataclass(frozen=True)
class Dialogue:
    text: str
    action: str


def _next_idle_action() -> str:
    """Randomize each round while ensuring every idle action is seen once."""
    if not _idle_action_bag:
        _idle_action_bag.extend(IDLE_ACTIONS)
        random.shuffle(_idle_action_bag)
    return _idle_action_bag.pop()


def _with_owner(text: str) -> str:
    if OWNER_NAME in text or random.random() >= OWNER_ADDRESS_PROBABILITY:
        return text
    return f"{OWNER_NAME}，{text}"


def event_line(event: str, **values: str) -> str:
    options = EVENT_LINES.get(event, ("灯火还在，我们再试一次。",))
    return _with_owner(random.choice(options).format(**values))


def idle_line() -> Dialogue:
    return Dialogue(
        text=_with_owner(random.choice(IDLE_LINES)),
        action=_next_idle_action(),
    )
