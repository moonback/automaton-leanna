import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import agent, improvements
from app.main import app


class PatchPathTests(unittest.TestCase):
    def test_accepts_backend_app_patch(self):
        patch_text = "diff --git a/backend/app/x.py b/backend/app/x.py\n--- a/backend/app/x.py\n+++ b/backend/app/x.py\n"
        self.assertIn("backend/app/x.py", improvements.check_patch_paths(patch_text))

    def test_rejects_rename_outside_backend_app(self):
        # A legitimate hunk keeps the old ---/+++ check satisfied; the pure rename has no such lines.
        patch_text = ("diff --git a/backend/app/ok.py b/backend/app/ok.py\n--- a/backend/app/ok.py\n"
                      "+++ b/backend/app/ok.py\n@@ -1 +1 @@\n-a\n+b\n"
                      "diff --git a/backend/app/x.py b/start.bat\nsimilarity index 100%\n"
                      "rename from backend/app/x.py\nrename to start.bat\n")
        with self.assertRaises(ValueError):
            improvements.check_patch_paths(patch_text)

    def test_rejects_symlink(self):
        patch_text = ("diff --git a/backend/app/l b/backend/app/l\nnew file mode 120000\n"
                      "--- /dev/null\n+++ b/backend/app/l\n@@ -0,0 +1 @@\n+../../.env\n")
        with self.assertRaises(ValueError):
            improvements.check_patch_paths(patch_text)


class ChatCompletionRetryTests(unittest.TestCase):
    def run_with(self, statuses):
        calls = []

        def handler(request):
            calls.append(request)
            status = statuses[len(calls) - 1]
            return httpx.Response(status, json={"choices": [{"message": {"content": "ok"}}]})

        async def scenario():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await agent.chat_completion(client, {"messages": []})

        with patch("app.agent.asyncio.sleep", new=AsyncMock()):
            return asyncio.run(scenario()), calls

    def test_retries_rate_limit_then_succeeds(self):
        result, calls = self.run_with([429, 503, 200])
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(len(calls), 3)

    def test_client_error_is_not_retried(self):
        with self.assertRaises(httpx.HTTPStatusError):
            self.run_with([400])

    def test_gives_up_after_last_attempt(self):
        with self.assertRaises(httpx.HTTPStatusError):
            self.run_with([429, 429, 429])


class ApiGuardTests(unittest.TestCase):
    # No `with`: lifespan (DB init, workers) is not started; guards reject before any route runs.
    client = TestClient(app, base_url="http://127.0.0.1")

    def test_foreign_host_rejected(self):
        self.assertEqual(self.client.get("/health", headers={"Host": "evil.example"}).status_code, 400)

    def test_local_host_allowed(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_bodyless_post_without_json_content_type_rejected(self):
        self.assertEqual(self.client.post("/objectives/1/supervise").status_code, 415)
        self.assertEqual(self.client.post("/tasks", content="x", headers={"Content-Type": "text/plain"}).status_code, 415)


if __name__ == "__main__":
    unittest.main()
