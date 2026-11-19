import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from app import windows_sandbox


class WindowsSandboxConfigTests(unittest.TestCase):
    def test_config_disables_network_clipboard_and_vgpu(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "test.wsb"
            workspace = root / "workspace"
            runtime = root / "python"
            venv = root / "venv"
            output = root / "output"
            for path in (workspace, runtime, venv, output):
                path.mkdir()
            windows_sandbox._write_config(config, workspace, runtime, output, venv)
            xml = ET.parse(config).getroot()
            values = {child.tag: child.text for child in xml if child.tag != "MappedFolders"}
            self.assertEqual(values["Networking"], "Disable")
            self.assertEqual(values["ClipboardRedirection"], "Disable")
            self.assertEqual(values["AudioInput"], "Disable")
            self.assertEqual(values["VideoInput"], "Disable")
            self.assertEqual(values["PrinterRedirection"], "Disable")
            self.assertEqual(values["vGPU"], "Disable")
            self.assertEqual(values["ProtectedClient"], "Enable")
            mappings = xml.find("MappedFolders").findall("MappedFolder")
            self.assertEqual(len(mappings), 4)
            self.assertEqual([item.findtext("ReadOnly") for item in mappings],
                             ["true", "true", "true", "false"])

    def test_config_without_venv_has_three_mappings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = [root / name for name in ("workspace", "python", "output")]
            for path in paths:
                path.mkdir()
            config = root / "test.wsb"
            windows_sandbox._write_config(config, paths[0], paths[1], paths[2])
            xml = ET.parse(config).getroot()
            self.assertEqual(len(xml.find("MappedFolders").findall("MappedFolder")), 3)

    def test_powershell_literal_escapes_single_quotes(self):
        self.assertEqual(windows_sandbox._powershell_literal("a'b"), "'a''b'")


if __name__ == "__main__":
    unittest.main()
