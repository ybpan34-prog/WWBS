"""WWBS 自动任务。"""

from tasks.dreamland import DEFAULT_GROUP_NAME
from tasks.models import AdbClient, ConfigStore, Step, WeeklyTask
from tasks.other import DAILY_ZONE_NAMES, DAILY_ZONE_TEMPLATES
from tasks.runner import TaskRunner

__all__ = [
    "DAILY_ZONE_NAMES",
    "DAILY_ZONE_TEMPLATES",
    "DEFAULT_GROUP_NAME",
    "AdbClient",
    "ConfigStore",
    "Step",
    "TaskRunner",
    "WeeklyTask",
]
