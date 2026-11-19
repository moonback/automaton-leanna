import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import sandbox


class SandboxRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace_patch = patch("app.sandbox.WORKSPACE", self.root)
        self.workspace_patch.start()

    def tearDown(self):
        self.workspace_patch.stop()
        self.temp.cleanup()

    def script(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def test_runs_workspace_script_with_isolated_interpreter(self):
        self.script("hello.py", "print('sandbox-ok')\n")
        result = sandbox.run_script("hello.py")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("sandbox-ok", result["stdout"])
        self.assertEqual(result["execution_profile"], "restricted_subprocess")
        self.assertIn(result["isolation_guarantee"],
                      {"windows_job_object_resource_containment", "posix_resource_limits"})

    def test_rejects_traversal_and_non_python_files(self):
        with self.assertRaises(ValueError):
            sandbox.resolve_script("../outside.py")
        self.script("notes.txt", "not python")
        with self.assertRaises(ValueError):
            sandbox.resolve_script("notes.txt")

    def test_rejects_invalid_timeout(self):
        self.script("hello.py", "print('ok')")
        with self.assertRaises(ValueError):
            sandbox.run_script("hello.py", timeout=0)

    def test_enforces_timeout(self):
        self.script("slow.py", "import time\ntime.sleep(5)\n")
        result = sandbox.run_script("slow.py", timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["returncode"], -1)


if __name__ == "__main__":
    unittest.main()
