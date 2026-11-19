"""Windows Sandbox launcher for scripts that need an OS security boundary.

Networking, clipboard and vGPU are disabled. The script directory and Python
runtime are read-only; a unique output directory is the only writable mapping.
"""
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SANDBOX_WORKSPACE = r"C:\AutomatonWorkspace"
SANDBOX_PYTHON = r"C:\AutomatonPython"
SANDBOX_VENV = r"C:\AutomatonVenv"
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
    # Use the base interpreter: a venv's pyvenv.cfg contains host-absolute paths.
    base = Path(sys.base_prefix).resolve()
    executable = base / "python.exe"
    if not executable.is_file() or not (base / "Lib").is_dir():
        raise ValueError("Runtime Python de base introuvable : Windows Sandbox refusé.")
    venv = Path(sys.prefix).resolve() if Path(sys.prefix).resolve() != base else None
    site_packages = venv / "Lib" / "site-packages" if venv else None
    if site_packages and not site_packages.is_dir():
        site_packages = None
        venv = None
    return base, executable.name, venv, site_packages


def _write_config(config_path, workspace, runtime, output, venv=None):
    root = ET.Element("Configuration")
    ET.SubElement(root, "vGPU").text = "Disable"
    ET.SubElement(root, "Networking").text = "Disable"
    ET.SubElement(root, "ClipboardRedirection").text = "Disable"
    ET.SubElement(root, "ProtectedClient").text = "Enable"
    ET.SubElement(root, "MemoryInMB").text = "2048"
    folders = ET.SubElement(root, "MappedFolders")
    mappings = [
        (workspace, SANDBOX_WORKSPACE, True),
        (runtime, SANDBOX_PYTHON, True),
    ]
    if venv:
        mappings.append((venv, SANDBOX_VENV, True))
    mappings.append((output, SANDBOX_OUTPUT, False))
    for host, guest, readonly in mappings:
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


def start(script, output_dir):
    """Launch a dedicated Windows Sandbox instance and return host process + paths."""
    executable = _sandbox_executable()
    runtime, python_name, venv, site_packages = _python_runtime()
    script = Path(script).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "process.log"
    exit_path = output_dir / "exit-code.txt"
    runner_path = output_dir / "run.ps1"
    python_guest = str(Path(SANDBOX_PYTHON) / python_name)
    script_guest = str(Path(SANDBOX_WORKSPACE) / script.name)

    guest_site = str(Path(SANDBOX_VENV) / "Lib" / "site-packages") if site_packages else None
    guest_log = str(Path(SANDBOX_OUTPUT) / "process.log")
    guest_exit = str(Path(SANDBOX_OUTPUT) / "exit-code.txt")
    runner_source = f"""
import runpy, site, sys, traceback
script_path = {script_guest!r}
log_path = {guest_log!r}
exit_path = {guest_exit!r}
site_packages = {guest_site!r}
if site_packages:
    site.addsitedir(site_packages)
class LimitedWriter:
    encoding = "utf-8"
    errors = "replace"
    def __init__(self, stream, limit):
        self.stream, self.limit, self.written, self.truncated = stream, limit, 0, False
        self.buffer = self
    def write(self, value):
        data = value if isinstance(value, bytes) else str(value).encode("utf-8", errors="replace")
        remaining = max(0, self.limit - self.written)
        if remaining:
            chunk = data[:remaining]
            self.stream.write(chunk)
            self.written += len(chunk)
        if len(data) > remaining:
            self.truncated = True
        return len(value)
    def flush(self): self.stream.flush()
    def isatty(self): return False
    def writable(self): return True
    def fileno(self): return self.stream.fileno()
    def writelines(self, lines):
        for line in lines: self.write(line)
code = 0
with open(log_path, "wb") as output:
    writer = LimitedWriter(output, 2 * 1024 * 1024 - 64)
    sys.stdout = writer
    sys.stderr = writer
    sys.argv = [script_path]
    try:
        runpy.run_path(script_path, run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:
        traceback.print_exc(file=writer)
        code = 1
    finally:
        if writer.truncated:
            output.write(b"\\n[Automaton: output truncated at 2 MiB]\\n")
        output.flush()
with open(exit_path, "w", encoding="ascii") as result:
    result.write(str(code))
sys.exit(code)
"""
    runner_path.write_text(runner_source, encoding="utf-8")
    powershell_path = output_dir / "run.ps1"
    powershell_path.write_text(
        "$ErrorActionPreference = 'Continue'\\n"
        f"& {_powershell_literal(str(Path(SANDBOX_PYTHON) / python_name))} -I -B "
        f"{_powershell_literal(str(Path(SANDBOX_OUTPUT) / 'runner.py'))}\\n"
        "$code = $LASTEXITCODE\\n"
        f"if (-not (Test-Path {_powershell_literal(guest_exit)})) {{ "
        f"Set-Content -LiteralPath {_powershell_literal(guest_exit)} -Value $code -NoNewline }}\\n"
        "exit $code\\n",
        encoding="utf-8"
    )
    config_path = output_dir.parent / f"{output_dir.name}.wsb"
    _write_config(config_path, script.parent, runtime, output_dir, venv)
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
    return process, log_path, exit_path, config_path
