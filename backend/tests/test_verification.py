import hashlib
import tempfile
import unittest
from pathlib import Path

from app.verification import verify_workspace


class WorkspaceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_exists_and_contains(self):
        self.write("result.txt", "build complete")
        result = verify_workspace([
            {"kind": "exists", "path": "result.txt"},
            {"kind": "contains", "path": "result.txt", "text": "complete"},
        ], self.root)
        self.assertTrue(result["success"])
        self.assertEqual(result["passed"], 2)

    def test_python_syntax_does_not_execute_code(self):
        marker = self.root / "executed.txt"
        self.write("safe.py", f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n")
        result = verify_workspace([{"kind": "python_syntax", "path": "safe.py"}], self.root)
        self.assertTrue(result["success"])
        self.assertFalse(marker.exists())

    def test_detects_invalid_python(self):
        self.write("broken.py", "def invalid(:\n pass\n")
        result = verify_workspace([{"kind": "python_syntax", "path": "broken.py"}], self.root)
        self.assertFalse(result["success"])

    def test_hash_and_change_detection(self):
        path = self.write("artifact.txt", "before")
        baseline = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertTrue(verify_workspace([{"kind": "sha256", "path": "artifact.txt", "expected": baseline}], self.root)["success"])
        path.write_text("after", encoding="utf-8")
        self.assertTrue(verify_workspace([{"kind": "changed_since", "path": "artifact.txt", "baseline_sha256": baseline}], self.root)["success"])

    def test_rejects_path_traversal_and_unknown_check(self):
        with self.assertRaises(ValueError):
            verify_workspace([{"kind": "exists", "path": "../outside"}], self.root)
        with self.assertRaises(ValueError):
            verify_workspace([{"kind": "execute", "path": "x.py"}], self.root)

    def test_missing_file_is_a_failed_check(self):
        result = verify_workspace([{"kind": "exists", "path": "missing.txt"}], self.root)
        self.assertFalse(result["success"])
        self.assertEqual(result["failed"], 1)


if __name__ == "__main__":
    unittest.main()
