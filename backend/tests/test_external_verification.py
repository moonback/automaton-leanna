import socket
import unittest
from unittest.mock import patch

from app.external_verification import normalize_checks, verify_external_checks


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.options = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        self.url = url
        return FakeResponse(200)


class ExternalVerificationTests(unittest.TestCase):
    def test_normalizes_loopback_http_and_tcp(self):
        checks = normalize_checks([
            {"kind": "http_status", "url": "http://127.0.0.1:8000/health"},
            {"kind": "tcp_port_open", "host": "localhost", "port": 8000},
        ])
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0]["expected_status"], 200)

    def test_rejects_non_loopback_and_unsafe_urls(self):
        for url in ("https://127.0.0.1/health", "http://example.com/", "http://user@127.0.0.1/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_checks([{"kind": "http_status", "url": url}])
        with self.assertRaises(ValueError):
            normalize_checks([{"kind": "tcp_port_open", "host": "192.168.1.5", "port": 80}])

    def test_rejects_invalid_status_and_port(self):
        with self.assertRaises(ValueError):
            normalize_checks([{"kind": "http_status", "url": "http://localhost/", "expected_status": 700}])
        with self.assertRaises(ValueError):
            normalize_checks([{"kind": "tcp_port_open", "port": 65536}])

    def test_http_status_check_records_observed_status(self):
        with patch("app.external_verification.httpx.Client", FakeClient):
            result = verify_external_checks([
                {"kind": "http_status", "url": "http://127.0.0.1:8000/health", "expected_status": 200}
            ])
        self.assertTrue(result["success"])
        self.assertEqual(result["checks"][0]["observed_status"], 200)

    def test_tcp_check_observes_a_local_listener(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            result = verify_external_checks([{"kind": "tcp_port_open", "host": "127.0.0.1", "port": port}])
            self.assertTrue(result["success"])
        finally:
            listener.close()

    def test_closed_tcp_port_fails_without_exception(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        result = verify_external_checks([{"kind": "tcp_port_open", "host": "127.0.0.1", "port": port}])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
