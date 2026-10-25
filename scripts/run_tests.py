"""Run GUI + threaded tests without finalizing Tcl objects off the main thread."""
import gc
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class MainThreadCleanup(unittest.TextTestResult):
    def startTest(self, test):
        # A destroyed Tk widget can remain in a Python reference cycle. The
        # next network worker must not be the thread that collects that cycle.
        gc.collect()
        super().startTest(test)


if __name__ == '__main__':
    gc.disable()
    try:
        suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), top_level_dir=str(ROOT/'tests'))
        outcome = unittest.TextTestRunner(verbosity=2, resultclass=MainThreadCleanup).run(suite)
        gc.collect()
        raise SystemExit(not outcome.wasSuccessful())
    finally:
        gc.enable()
