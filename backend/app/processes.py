"""Lifecycle manager for Python workspace processes started by Automaton."""
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import db
from .config import DATA, WORKSPACE
from .sandbox import resolve_script, safe_environment, _limits, MAX_TIMEOUT

LOG_DIR = DATA / "process-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOCK = threading.RLock()
_HANDLES = {}
_LOG_THREADS = {}
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
            stopped_at DATETIME
        )""")
        conn.execute("""UPDATE managed_processes SET status='orphaned',
            updated_at=CURRENT_TIMESTAMP
            WHERE status IN ('starting','running','stopping')""")


def _record(process_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM managed_processes WHERE id=?", (process_id,)).fetchone()
    return dict(row) if row else None


def _refresh(process_id):
    with _LOCK:
        handle = _HANDLES.get(process_id)
        if handle is not None:
            code = handle.poll()
            if code is not None:
                with db.connect() as conn:
                    conn.execute("""UPDATE managed_processes SET status='exited',exit_code=?,
                        updated_at=CURRENT_TIMESTAMP,stopped_at=CURRENT_TIMESTAMP
                        WHERE id=? AND status IN ('running','stopping')""", (code, process_id))
                _HANDLES.pop(process_id, None)
                _LOG_THREADS.pop(process_id, None)
    return _record(process_id)


def start(script_path):
    script = resolve_script(script_path)
    token = uuid.uuid4().hex
    log_path = LOG_DIR / f"process-{token}.log"
    command = [os.sys.executable, "-I", "-B", str(script)]
    kwargs = {"cwd": str(WORKSPACE), "env": safe_environment(), "stdin": subprocess.DEVNULL,
              "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "shell": False}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = _limits(cpu_seconds=3600)
    process = subprocess.Popen(command, **kwargs)

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
        cur = conn.execute("""INSERT INTO managed_processes(token,pid,script,status,log_path)
            VALUES(?,?,?,'running',?)""", (token, process.pid, str(script.relative_to(WORKSPACE)), str(log_path)))
        process_id = cur.lastrowid
    with _LOCK:
        _HANDLES[process_id] = process
        _LOG_THREADS[process_id] = reader
    return _refresh(process_id)


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
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=5, check=False)
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
