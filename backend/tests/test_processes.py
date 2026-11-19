import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, processes, sandbox


class ManagedProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace_patch = patch("app.sandbox.WORKSPACE", self.root)
        self.process_workspace_patch = patch("app.processes.WORKSPACE", self.root)
        self.data_patch = patch("app.processes.DATA", self.root / "data")
        self.log_patch = patch("app.processes.LOG_DIR", self.root / "data" / "process-logs")
        self.db_patch = patch("app.db.DB", self.root / "test.db")
        for item in (self.workspace_patch, self.process_workspace_patch, self.data_patch,
                     self.log_patch, self.db_patch):
            item.start()
        processes.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.script = self.root / "worker.py"
        self.script.write_text("import time\nwhile True: time.sleep(0.2)\n", encoding="utf-8")
        processes.init()

    def tearDown(self):
        for item in (self.db_patch, self.log_patch, self.data_patch,
                     self.process_workspace_patch, self.workspace_patch):
            item.stop()
        self.temp.cleanup()

    def test_start_list_logs_and_stop_owned_process(self):
        record = processes.start("worker.py")
        self.assertEqual(record["status"], "running")
        self.assertGreater(record["pid"], 0)
        log = processes.read_log(record["id"])
        self.assertIsNotNone(log)
        stopped = processes.stop(record["id"])
        self.assertEqual(stopped["status"], "exited")
        self.assertIsNone(processes.stop(99999))

    def test_restart_marks_running_process_and_applies_platform_cleanup(self):
        record = processes.start("worker.py")
        process = processes._HANDLES[record["id"]]
        processes.init()
        current = processes.get_process(record["id"])
        expected = "interrupted" if os.name == "nt" else "orphaned"
        self.assertEqual(current["status"], expected)
        self.assertIsNone(processes._HANDLES.get(record["id"]))
        if os.name == "nt":
            process.wait(timeout=3)
            self.assertIsNotNone(process.poll())
        else:
            # POSIX fallback does not own a persistent OS job object.
            process.terminate()
            process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
