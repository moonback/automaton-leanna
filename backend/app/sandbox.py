"""Constrained subprocess execution for workspace Python scripts.

This is a resource-constrained subprocess, not a security-grade OS sandbox:
Python code can still access files and network resources available to the user.
"""
import os
import subprocess
import sys
from pathlib import Path

from .config import WORKSPACE, DATA

MAX_SCRIPT_BYTES = 200_000
MAX_OUTPUT_CHARS = 8_000
DEFAULT_TIMEOUT = 15
MAX_TIMEOUT = 30
MAX_MEMORY_BYTES = 512 * 1024 * 1024


def resolve_script(relative_path):
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("Chemin de script requis.")
    candidate = (WORKSPACE / relative_path).resolve()
    root = WORKSPACE.resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Exécution limitée aux scripts du workspace.")
    if candidate.suffix.lower() != ".py" or not candidate.is_file():
        raise ValueError("Seuls les scripts Python existants du workspace sont autorisés.")
    if candidate.stat().st_size > MAX_SCRIPT_BYTES:
        raise ValueError("Script trop volumineux (limite 200 Ko).")
    return candidate


def _limits(cpu_seconds=MAX_TIMEOUT):
    if os.name == "nt":
        return None
    try:
        import resource
    except ImportError:
        return None

    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
    return apply


def safe_environment():
    allowed = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "HOME")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def run_script(relative_path, timeout=DEFAULT_TIMEOUT):
    script = resolve_script(relative_path)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT:
        raise ValueError(f"timeout doit être compris entre 1 et {MAX_TIMEOUT} secondes.")
    command = [sys.executable, "-I", "-B", str(script)]
    kwargs = {
        "cwd": str(WORKSPACE),
        "env": safe_environment(),
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = _limits()
    try:
        result = subprocess.run(command, **kwargs)
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-MAX_OUTPUT_CHARS:],
            "stderr": result.stderr[-MAX_OUTPUT_CHARS:],
            "timed_out": False,
            "execution_profile": "restricted_subprocess",
            "isolation_guarantee": "resource_limits_only",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": -1,
            "stdout": (exc.stdout or "")[-MAX_OUTPUT_CHARS:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-MAX_OUTPUT_CHARS:] if isinstance(exc.stderr, str) else "",
            "timed_out": True,
            "execution_profile": "restricted_subprocess",
            "isolation_guarantee": "resource_limits_only",
        }
