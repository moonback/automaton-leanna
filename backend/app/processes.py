"""Lifecycle manager for Python workspace processes started by Automaton."""
import os
import signal
import subprocess
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import db
from .config import DATA, WORKSPACE
from .sandbox import resolve_script, safe_environment, _limits, MAX_TIMEOUT
from . import windows_job, windows_sandbox

LOG_DIR = DATA / "process-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOCK = threading.RLock()
_HANDLES = {}
_LOG_THREADS = {}
_JOB_HANDLES = {}
MAX_LOG_BYTES = 2 * 1024 * 1024


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, ProcessLookupError):
        return False


def init():
    """Mark previously running records orphaned; never signal a PID after restart."""
    with _LOCK:
        _HANDLES.clear()
        _LOG_THREADS.clear()
        for job in _JOB_HANDLES.values():
            windows_job.close_job(job)
        _JOB_HANDLES.clear()
    restart_status = "interrupted" if os.name == "nt" else "orphaned"
    with db.connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS managed_processes (
            id INTEGER PRIMARY KEY,
            token TEXT NOT NULL UNIQUE,
            pid INTEGER NOT NULL,
            script TEXT NOT NULL,
            status TEXT NOT NULL,
            log_path TEXT NOT NULL,
            exit_code INTEGER,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            stopped_at DATETIME,
            isolation TEXT NOT NULL DEFAULT 'job_object',
            exit_path TEXT,
            sandbox_config_path TEXT
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(managed_processes)").fetchall()}
        for name, declaration in (("isolation", "TEXT NOT NULL DEFAULT 'job_object'"), ("exit_path", "TEXT"), ("sandbox_config_path", "TEXT")):
            if name not in columns:
                conn.execute(f"ALTER TABLE managed_processes ADD COLUMN {name} {declaration}")
        conn.execute("""UPDATE managed_processes SET status=?,
            updated_at=CURRENT_TIMESTAMP,stopped_at=CURRENT_TIMESTAMP
            WHERE status IN ('starting','running','stopping')""", (restart_status,))


def _record(process_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM managed_processes WHERE id=?", (process_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    mode = result.get("isolation") or "job_object"
    result["isolation_profile"] = "windows_sandbox" if mode == "windows_sandbox" else ("windows_job_object" if os.name == "nt" else "posix_resource_limits")
    result["security_boundary"] = "windows_sandbox" if mode == "windows_sandbox" else "resource_containment_only"
    return result


def _refresh(process_id):
    with _LOCK:
        handle = _HANDLES.get(process_id)
        if handle is not None:
            code = handle.poll()
            if code is not None:
                record = _record(process_id)
                exit_code = code
                if record and record.get("isolation") == "windows_sandbox":
                    exit_code = None
                    exit_path = record.get("exit_path")
                    if exit_path and Path(exit_path).is_file():
                        try:
                            exit_code = int(Path(exit_path).read_text(encoding="utf-8").strip())
                        except (OSError, ValueError):
                            exit_code = None
                    config_path = record.get("sandbox_config_path")
                    if config_path:
                        try:
                            Path(config_path).unlink(missing_ok=True)
                        except OSError:
                            pass
                    try:
                        (Path(record["log_path"]).parent / "run.ps1").unlink(missing_ok=True)
                    except OSError:
                        pass
                with db.connect() as conn:
                    conn.execute("""UPDATE managed_processes SET status='exited',exit_code=?,
                        updated_at=CURRENT_TIMESTAMP,stopped_at=CURRENT_TIMESTAMP
                        WHERE id=? AND status IN ('running','stopping')""", (exit_code, process_id))
                _HANDLES.pop(process_id, None)
                _LOG_THREADS.pop(process_id, None)
                job = _JOB_HANDLES.pop(process_id, None)
                if job:
                    windows_job.close_job(job)
    return _record(process_id)


def start(script_path, isolation="job_object"):
    script = resolve_script(script_path)
    if isolation not in {"job_object", "windows_sandbox"}:
        raise ValueError("Profil d'isolation inconnu.")
    if isolation == "windows_sandbox" and os.name != "nt":
        raise ValueError("Windows Sandbox est disponible uniquement sous Windows.")
    if isolation == "windows_sandbox":
        with db.connect() as conn:
            active = conn.execute(
                "SELECT id FROM managed_processes WHERE isolation='windows_sandbox' AND status IN ('starting','running','stopping') LIMIT 1"
            ).fetchone()
        if active:
            raise ValueError("Une seule session Windows Sandbox peut être active à la fois.")

    token = uuid.uuid4().hex
    output_dir = LOG_DIR / f"sandbox-{token}"
    log_path = LOG_DIR / f"process-{token}.log"
    exit_path = None
    config_path = None
    job = None
    reader = None

    if isolation == "windows_sandbox":
        process, log_path, exit_path, config_path = windows_sandbox.start(script, output_dir)
    else:
        command = [os.sys.executable, "-I", "-B", str(script)]
        kwargs = {"cwd": str(WORKSPACE), "env": safe_environment(), "stdin": subprocess.DEVNULL,
                  "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "shell": False}
        if os.name == "nt":
            kwargs["creationflags"] = windows_job.CREATE_SUSPENDED | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
            kwargs["preexec_fn"] = _limits(cpu_seconds=3600)
        process = subprocess.Popen(command, **kwargs)
        if os.name == "nt":
            try:
                job = windows_job.create_job_for_suspended_process(
                    process, memory_bytes=512 * 1024 * 1024, cpu_seconds=3600, max_processes=32
                )
            except Exception:
                process.kill()
                process.wait()
                raise

        def drain_output(pipe, destination):
            written = 0
            try:
                with open(destination, "ab", buffering=0) as output:
                    while True:
                        chunk = pipe.read(8192)
                        if not chunk:
                            break
                        remaining = MAX_LOG_BYTES - written
                        if remaining > 0:
                            output.write(chunk[:remaining])
                            written += min(len(chunk), remaining)
                    if written >= MAX_LOG_BYTES:
                        output.write(b"\n[Automaton: log limit reached; further output discarded]\n")
            finally:
                pipe.close()

        reader = threading.Thread(target=drain_output, args=(process.stdout, log_path), daemon=True)
        reader.start()

    with db.connect() as conn:
        cur = conn.execute("""INSERT INTO managed_processes(
            token,pid,script,status,log_path,isolation,exit_path,sandbox_config_path
        ) VALUES(?,?,?,'running',?,?,?,?)""", (
            token, process.pid, str(script.relative_to(WORKSPACE)), str(log_path),
            isolation, str(exit_path) if exit_path else None,
            str(config_path) if config_path else None
        ))
        process_id = cur.lastrowid
    with _LOCK:
        _HANDLES[process_id] = process
        if reader:
            _LOG_THREADS[process_id] = reader
        if job:
            _JOB_HANDLES[process_id] = job
    return _refresh(process_id)


def shutdown():
    """Stop processes owned by this backend before releasing native handles."""
    with _LOCK:
        process_ids = list(_HANDLES)
    for process_id in process_ids:
        try:
            stop(process_id)
        except Exception:
            pass
    with _LOCK:
        for job in _JOB_HANDLES.values():
            windows_job.close_job(job)
        _JOB_HANDLES.clear()


def list_processes(limit=50):
    with db.connect() as conn:
        rows = conn.execute("SELECT id FROM managed_processes ORDER BY id DESC LIMIT ?",
                            (max(1, min(int(limit), 200)),)).fetchall()
    return [_refresh(row["id"]) for row in rows]


def get_process(process_id):
    return _refresh(process_id)


def stop(process_id):
    with _LOCK:
        process = _HANDLES.get(process_id)
        record = _record(process_id)
        if record is None:
            return None
        if process is None:
            # Only handles created in this backend lifetime are stoppable.
            return record
        if process.poll() is not None:
            return _refresh(process_id)
        with db.connect() as conn:
            conn.execute("UPDATE managed_processes SET status='stopping',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (process_id,))
        try:
            if record.get("isolation") == "windows_sandbox":
                process.terminate()
            elif os.name == "nt":
                windows_job.terminate_job(_JOB_HANDLES.get(process_id))
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        except ProcessLookupError:
            pass
        return _refresh(process_id)


def read_log(process_id, max_bytes=12000):
    record = get_process(process_id)
    if record is None:
        return None
    path = Path(record["log_path"]).resolve()
    root = LOG_DIR.resolve()
    if root not in path.parents or not path.is_file():
        return {"process": record, "log": ""}
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - max_bytes))
        content = stream.read(max_bytes).decode("utf-8", errors="replace")
    return {"process": record, "log": content}
