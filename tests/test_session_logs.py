import queue
import tempfile
import threading
import unittest
from pathlib import Path

from app import App
from session_logs import create_session_log, prune_session_logs


class SessionLogTests(unittest.TestCase):
    def test_keeps_three_latest_launches_and_leaves_other_files_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "logs"
            directory.mkdir()
            older_logs = [
                directory / f"wwbs-20261101T12000000000{number}Z-{'a' * 32}.log"
                for number in range(4)
            ]
            for path in older_logs:
                path.touch()
            other = directory / "update.log"
            other.touch()
            current = create_session_log(directory)

            prune_session_logs(directory)

            self.assertEqual(set(directory.iterdir()), {*older_logs[2:], current, other})

    def test_runtime_message_is_readable_from_disk_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = App.__new__(App)
            app._log_lock = threading.Lock()
            app.log_queue = queue.Queue()
            app._session_log_path = create_session_log(Path(temporary))
            app._log("进入每日活跃度")
            app._log("领取成功")

            saved = app._session_log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(saved, [app.log_queue.get_nowait(), app.log_queue.get_nowait()])
            self.assertTrue(saved[-1].endswith("领取成功"))


if __name__ == "__main__":
    unittest.main()
