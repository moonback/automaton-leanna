"""Windows Sandbox launcher for scripts that need an OS security boundary.

The guest has networking, clipboard and vGPU disabled. Only the script's
parent folder and the Python runtime are mounted read-only; a per-run folder
is the sole writable host mapping and contains only runner/output artifacts.
"""
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .config import DATA

SANDBOX_WORKSPACE = r"C:\AutomatonWorkspace"
SANDBOX_PYTHON = r"C:\AutomatonPython"
SANDBOX_OUTPUT = r"C:\AutomatonOutput"


def _powershell_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _sandbox_executable():
    if os.name != "nt":
        raise ValueError("Windows Sandbox est disponible uniquement sous Windows.")
    candidate = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsSandbox.exe"
    found = str(candidate) if candidate.is_file() else shutil.which("WindowsSandbox.exe")
    if not found:
        raise ValueError(
            "Windows Sandbox est indisponible. Activez la fonctionnalité Windows Sandbox "
            "sur Windows Pro/Entreprise/Éducation, puis redémarrez."
        )
    return found


def _python_runtime():
    # Use the base interpreter inside the guest. A venv's pyvenv.cfg contains
    # host-absolute paths, so mount its site-packages separately instead.
    base = Path(sys.base_prefix).resolve()
    executable = base / "python.exe"
    if not executable.is_file() or not (base / "Lib").is_dir():
        raise ValueError("Runtime Python de base introuvable : Windows Sandbox refusé.")
    venv = Path(sys.prefix).resolve() if Path(sys.prefix).resolve() != base else None
    site_packages = venv / "Lib" / "site-packages" if venv else None
    if site_packages and not site_packages.is_dir():
        site_packages = None
    return base, executable.name, venv, site_packages


def _write_config(config_path, workspace, runtime, output):
    root = ET.Element("Configuration")
    ET.SubElement(root, "vGPU").text = "Disable"
    ET.SubElement(root, "Networking").text = "Disable"
    ET.SubElement(root, "ClipboardRedirection").text = "Disable"
    ET.SubElement(root, "ProtectedClient").text = "Enable"
    ET.SubElement(root, "MemoryInMB").text = "2048"
    folders = ET.SubElement(root, "MappedFolders")
    for host, guest, readonly in (
        (workspace, SANDBOX_WORKSPACE, True),
        (runtime, SANDBOX_PYTHON, True),
        *(([(venv, r"C:\\AutomatonVenv", True)] if venv else [])),
        (output, SANDBOX_OUTPUT, False),
    ):
        entry = ET.SubElement(folders, "MappedFolder")
        ET.SubElement(entry, "HostFolder").text = str(host)
        ET.SubElement(entry, "SandboxFolder").text = guest
        ET.SubElement(entry, "ReadOnly").text = "true" if readonly else "false"
    command = ET.SubElement(ET.SubElement(root, "LogonCommand"), "Command")
    command.text = (
        "powershell.exe -NoLogo -NoProfile -NonInteractive "
        "-ExecutionPolicy Bypass -File C:\\AutomatonOutput\\run.ps1"
    )
    ET.ElementTree(root).write(config_path, encoding="utf-8", xml_declaration=True)


def start(script, output_dir, log_path):
    """Launch a dedicated Windows Sandbox instance; return its host process."""
    executable = _sandbox_executable()
    runtime, python_name, venv, site_packages = _python_runtime()
    script = Path(script).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path).resolve()
    exit_path = output_dir / "exit-code.txt"
    runner_path = output_dir / "run.ps1"
    python_guest = str(Path(SANDBOX_PYTHON) / python_relative.as_posix()).replace("/", "\\")
    script_guest = str(Path(SANDBOX_WORKSPACE) / script.name).replace("/", "\\")
    runner = (
        "$ErrorActionPreference = 'Continue'\n"
        f"& {_powershell_literal(python_guest)} -I -B {_powershell_literal(script_guest)} "
        f"*> {_powershell_literal(str(Path(SANDBOX_OUTPUT) / 'process.log'))}\n"
        "$code = $LASTEXITCODE\n"
        f"Set-Content -LiteralPath {_powershell_literal(str(Path(SANDBOX_OUTPUT) / 'exit-code.txt'))} "
        "-Value $code -NoNewline\n"
        "exit $code\n"
    )
    runner_path.write_text(runner, encoding="utf-8")
    config_path = output_dir.parent / f"{output_dir.name}.wsb"
    _write_config(config_path, script.parent, runtime, output_dir)
    # The guest writes to the mapped output folder. The host log endpoint reads
    # that exact file; no guest-controlled path is accepted.
    actual_log = output_dir / "process.log"
    try:
        process = subprocess.Popen(
            [executable, str(config_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except OSError:
        shutil.rmtree(output_dir, ignore_errors=True)
        try:
            config_path.unlink()
        except OSError:
            pass
        raise
    return process, actual_log, exit_path, config_path
