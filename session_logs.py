import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


_SESSION_NAME = re.compile(r"wwbs-\d{8}T\d{12}Z-[0-9a-f]{32}\.log")


def create_session_log(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"wwbs-{timestamp}-{uuid4().hex}.log"
    path.touch(exist_ok=False)
    return path


def prune_session_logs(directory: Path) -> None:
    sessions = sorted(
        (entry for entry in directory.iterdir() if _SESSION_NAME.fullmatch(entry.name) and entry.is_file()),
        reverse=True,
    )
    for old in sessions[3:]:
        old.unlink(missing_ok=True)
