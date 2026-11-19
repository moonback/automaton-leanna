import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, permissions


class PermissionManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch("app.db.DB", Path(self.temp.name) / "permissions.db")
        self.db_patch.start()
        permissions.init()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_default_profile_denies_write(self):
        self.assertEqual(permissions.get_config()["profile"], "observe_only")
        called = []
        result = permissions.dispatch("write_file", {"path": "x.txt", "content": "hello"},
                                      lambda name, args: called.append(name))
        self.assertIn("error", result)
        self.assertEqual(called, [])

    def test_workspace_write_allows_workspace_tools(self):
        permissions.set_profile("workspace_write")
        result = permissions.dispatch("write_file", {"path": "x.txt", "content": "secret"},
                                      lambda name, args: "written")
        self.assertEqual(result, "written")
        audit = permissions.list_audit()
        self.assertNotIn("secret", str(audit))
        self.assertIn("sha256", str(audit))

    def test_sensitive_action_requires_one_shot_approval(self):
        permissions.set_profile("sandbox_execution")
        called = []
        result = permissions.dispatch("start_process", {"path": "worker.py"},
                                      lambda name, args: called.append((name, args)) or {"started": True})
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(called, [])
        request_id = result["request_id"]
        approved = permissions.decide(request_id, True,
                                      lambda name, args: called.append((name, args)) or {"started": True})
        self.assertEqual(approved["status"], "executed")
        self.assertEqual(len(called), 1)
        with self.assertRaises(ValueError):
            permissions.decide(request_id, True, lambda name, args: None)

    def test_denied_approval_never_executes(self):
        permissions.set_profile("admin")
        result = permissions.dispatch("run_python", {"path": "task.py"}, lambda *_: None)
        called = []
        decision = permissions.decide(result["request_id"], False,
                                      lambda *args: called.append(args))
        self.assertEqual(decision["status"], "denied")
        self.assertFalse(called)

    def test_audit_is_append_only(self):
        permissions.set_profile("workspace_write")
        permissions.dispatch("remember", {"content": "private fact"},
                             lambda *_: "ok")
        with self.assertRaises(Exception):
            with db.connect() as conn:
                conn.execute("DELETE FROM permission_audit")
        self.assertTrue(permissions.list_audit())


if __name__ == "__main__":
    unittest.main()
