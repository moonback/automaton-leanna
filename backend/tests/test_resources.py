import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import resources


class ResourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        (self.workspace / "sample.txt").write_text("automaton", encoding="utf-8")
        self.workspace_patch = patch.object(resources, "WORKSPACE", self.workspace)
        self.workspace_patch.start()

    def tearDown(self):
        self.workspace_patch.stop()
        self.temp.cleanup()

    def test_snapshot_reports_metrics_processes_and_threshold_alerts(self):
        memory = SimpleNamespace(total=1000, available=100, used=900, percent=90.0)
        disk_usage = SimpleNamespace(total=2000, used=1900, free=100, percent=95.0)
        net = SimpleNamespace(bytes_sent=10, bytes_recv=20, packets_sent=1, packets_recv=2)
        settings = {"cpu_warning": 80.0, "memory_warning": 80.0, "disk_warning": 90.0}
        with patch.object(resources.psutil, "cpu_percent", return_value=85.0), \
             patch.object(resources.psutil, "virtual_memory", return_value=memory), \
             patch.object(resources.psutil, "disk_usage", return_value=disk_usage), \
             patch.object(resources.psutil, "net_io_counters", return_value=net), \
             patch.object(resources.psutil, "cpu_count", side_effect=[8, 4]), \
             patch.object(resources.psutil, "process_iter", return_value=[]), \
             patch.object(resources.shutil, "disk_usage", return_value=disk_usage):
            result = resources.snapshot(settings)

        self.assertEqual(result["cpu"]["percent"], 85.0)
        self.assertEqual(result["memory"]["percent"], 90.0)
        self.assertEqual(result["storage"]["percent"], 95.0)
        self.assertEqual(result["network"]["bytes_received"], 20)
        self.assertEqual({alert["metric"] for alert in result["alerts"]}, {"cpu", "memory", "disk"})
        self.assertEqual(result["workspace"]["file_count"], 1)
        self.assertEqual(result["processes"], [])
        self.assertFalse(result["gpu"]["available"])


if __name__ == "__main__":
    unittest.main()
