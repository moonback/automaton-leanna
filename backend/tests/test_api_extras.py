import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, processes
from app.main import app


class ApiExtrasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "ws").mkdir()
        (root / "ws" / "note.md").write_text("bonjour", encoding="utf-8")
        self.patches = [patch("app.db.DB", root / "test.db"), patch("app.tools.WORKSPACE", root / "ws")]
        for item in self.patches:
            item.start()
        db.init()
        processes.init()
        # No `with`: lifespan workers are not started.
        self.client = TestClient(app, base_url="http://127.0.0.1")

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def test_workspace_file_preview(self):
        response = self.client.get("/workspace/file", params={"path": "note.md"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "bonjour")

    def test_workspace_file_rejects_traversal_and_missing(self):
        self.assertEqual(self.client.get("/workspace/file", params={"path": "../test.db"}).status_code, 400)
        self.assertEqual(self.client.get("/workspace/file", params={"path": "absent.md"}).status_code, 404)

    def test_summary_counts(self):
        db.create_task("a")
        db.create_task("b")
        claimed = db.claim_task()
        db.finish_task(claimed["id"], "succeeded")
        db.claim_task()
        db.create_task("c")
        summary = self.client.get("/summary").json()
        self.assertEqual((summary["tasks_queued"], summary["tasks_running"], summary["tasks_succeeded"]), (1, 1, 1))
        self.assertEqual(summary["processes_running"], 0)


if __name__ == "__main__":
    unittest.main()
