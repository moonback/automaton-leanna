import unittest

from app import resources


class ResourceSnapshotTests(unittest.TestCase):
    def test_snapshot_exposes_system_telemetry(self):
        snapshot = resources.snapshot()

        self.assertIn("workspace", snapshot)
        self.assertIn("storage", snapshot)
        self.assertIn("system", snapshot)

        system = snapshot["system"]
        for key in (
            "cpu_percent",
            "memory_percent",
            "memory_used_bytes",
            "memory_total_bytes",
            "disk_percent",
            "network_sent_bytes",
            "network_received_bytes",
            "gpu_available",
        ):
            self.assertIn(key, system)

        self.assertGreaterEqual(system["cpu_percent"], 0)
        self.assertGreaterEqual(system["memory_percent"], 0)
        self.assertGreater(system["memory_total_bytes"], 0)
        self.assertGreater(snapshot["storage"]["total_bytes"], 0)

    def test_disk_usage_receives_string_path(self):
        from unittest.mock import patch

        with patch("app.resources.shutil.disk_usage", wraps=resources.shutil.disk_usage) as disk_usage:
            resources.snapshot()
            self.assertIsInstance(disk_usage.call_args.args[0], str)


if __name__ == "__main__":
    unittest.main()
