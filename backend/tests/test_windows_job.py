import os
import subprocess
import sys
import unittest

from app import windows_job


class WindowsJobObjectTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Job Objects are Windows-only")
    def test_assign_limits_and_terminate_suspended_process(self):
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
            creationflags=windows_job.CREATE_SUSPENDED,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        job = None
        try:
            job = windows_job.create_job_for_suspended_process(
                process, memory_bytes=128 * 1024 * 1024, cpu_seconds=10, max_processes=4
            )
            self.assertIsNotNone(job)
            windows_job.terminate_job(job)
            self.assertIsNotNone(process.wait(timeout=5))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if job:
                windows_job.close_job(job)

    @unittest.skipUnless(os.name != "nt", "Non-Windows fallback test")
    def test_non_windows_is_a_noop(self):
        self.assertIsNone(windows_job.create_job_for_suspended_process(None))


if __name__ == "__main__":
    unittest.main()
