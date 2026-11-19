import unittest

from unittest.mock import patch

from app.objective_verification import normalize_checks, _run_checks


class ObjectiveAcceptanceCheckTests(unittest.TestCase):
    def test_accepts_supported_checks(self):
        checks = normalize_checks([
            {"kind": "exists", "path": "report.md"},
            {"kind": "contains", "path": "report.md", "text": "Conclusion"},
            {"kind": "python_syntax", "path": "src/main.py"},
        ])
        self.assertEqual(len(checks), 3)

    def test_rejects_missing_checks(self):
        with self.assertRaises(ValueError):
            normalize_checks([])

    def test_rejects_unknown_or_unsafe_check(self):
        with self.assertRaises(ValueError):
            normalize_checks([{"kind": "execute", "path": "script.py"}])
        with self.assertRaises(ValueError):
            normalize_checks([{"kind": "exists", "path": "/outside.txt"}])

    def test_contains_requires_expected_text(self):
        with self.assertRaises(ValueError):
            normalize_checks([{"kind": "contains", "path": "report.md"}])

    def test_accepts_loopback_external_checks(self):
        checks = normalize_checks([
            {"kind": "http_status", "url": "http://127.0.0.1:8000/health", "expected_status": 200},
            {"kind": "tcp_port_open", "host": "localhost", "port": 8000},
        ])
        self.assertEqual(checks[0]["kind"], "http_status")
        self.assertEqual(checks[1]["kind"], "tcp_port_open")

    def test_rejects_public_network_checks_in_objective_plan(self):
        with self.assertRaises(ValueError):
            normalize_checks([{"kind": "http_status", "url": "http://example.com/"}])

    def test_combines_workspace_and_external_evidence(self):
        workspace = {"checks": [{"kind": "exists", "path": "result.txt", "passed": True}]}
        external = {"checks": [{"kind": "tcp_port_open", "host": "127.0.0.1", "port": 8000, "passed": True}]}
        with patch("app.objective_verification.workspace_verification.verify_workspace", return_value=workspace):
            with patch("app.objective_verification.external_verification.verify_external_checks", return_value=external):
                result = _run_checks([
                    {"kind": "exists", "path": "result.txt"},
                    {"kind": "tcp_port_open", "host": "127.0.0.1", "port": 8000},
                ])
        self.assertTrue(result["success"])
        self.assertEqual(result["total"], 2)
        self.assertEqual([item["index"] for item in result["checks"]], [0, 1])


if __name__ == "__main__":
    unittest.main()
