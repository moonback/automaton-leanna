"""Capability-based tool permissions, one-shot approvals and append-only audit trail."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from . import db

PROFILES = {
    "observe_only": {"list_files", "read_file", "list_processes", "recall_memories"},
    "workspace_write": {"list_files", "read_file", "list_processes", "recall_memories", "write_file", "remember"},
    "sandbox_execution": {"list_files", "read_file", "list_processes", "recall_memories", "write_file", "remember", "run_python", "start_process"},
    "admin": {"*"},
}
SENSITIVE_TOOLS = {"run_python", "start_process", "stop_process"}
VALID_TOOLS = {
    "list_files", "read_file", "write_file", "run_python", "start_process",
    "list_processes", "stop_process", "recall_memories", "remember",
}
DEFAULT_PROFILE = "observe_only"
APPROVAL_TTL_MINUTES = 10


def init():
    with db.connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS permission_config (
            id INTEGER PRIMARY KEY CHECK(id=1),
            profile TEXT NOT NULL DEFAULT 'observe_only',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("INSERT OR IGNORE INTO permission_config(id,profile) VALUES(1,?)", (DEFAULT_PROFILE,))
        conn.execute("""CREATE TABLE IF NOT EXISTS permission_requests (
            id INTEGER PRIMARY KEY,
            tool TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            arguments_summary TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','expired','executed','failed')),
            expires_at TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            decided_at DATETIME,
            result_summary TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS permission_audit (
            id INTEGER PRIMARY KEY,
            event TEXT NOT NULL,
            tool TEXT NOT NULL,
            arguments_summary TEXT NOT NULL,
            decision TEXT NOT NULL,
            actor TEXT NOT NULL,
            result_summary TEXT NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS permission_audit_no_update
            BEFORE UPDATE ON permission_audit BEGIN SELECT RAISE(ABORT,'audit log is append-only'); END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS permission_audit_no_delete
            BEFORE DELETE ON permission_audit BEGIN SELECT RAISE(ABORT,'audit log is append-only'); END""")
        conn.execute("""UPDATE permission_requests SET status='expired'
            WHERE status='pending' AND expires_at <= ?""", (_now(),))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _summary(arguments):
    safe = {}
    for key, value in (arguments or {}).items():
        if re.search(r"(key|token|secret|password|authorization|credential)", key, re.I):
            safe[key] = "[REDACTED]"
        elif key in {"content", "patch"} and isinstance(value, str):
            safe[key] = {"length": len(value), "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()}
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value[:300] if isinstance(value, str) else value
        else:
            safe[key] = f"[{type(value).__name__}]"
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)[:2000]


def _audit(event, tool, summary, decision, actor, result=""):
    with db.connect() as conn:
        conn.execute("""INSERT INTO permission_audit(event,tool,arguments_summary,decision,actor,result_summary)
            VALUES(?,?,?,?,?,?)""", (event, tool, summary, decision, actor, str(result)[:1000]))


def get_config():
    with db.connect() as conn:
        row = conn.execute("SELECT profile,updated_at FROM permission_config WHERE id=1").fetchone()
    return {"profile": row["profile"], "updated_at": row["updated_at"], "available_profiles": list(PROFILES)}


def set_profile(profile, actor="user"):
    if profile not in PROFILES:
        raise ValueError("Profil de confiance inconnu.")
    with db.connect() as conn:
        conn.execute("UPDATE permission_config SET profile=?,updated_at=CURRENT_TIMESTAMP WHERE id=1", (profile,))
    _audit("profile_changed", "permissions", _summary({"profile": profile}), "allowed", actor, "Profil mis à jour")
    return get_config()


def _request(tool, arguments, summary):
    expires = (datetime.now(timezone.utc) + timedelta(minutes=APPROVAL_TTL_MINUTES)).isoformat()
    with db.connect() as conn:
        cur = conn.execute("""INSERT INTO permission_requests
            (tool,arguments_json,arguments_summary,status,expires_at) VALUES(?,?,?,'pending',?)""",
            (tool, json.dumps(arguments, ensure_ascii=False), summary, expires))
        request_id = cur.lastrowid
    _audit("approval_requested", tool, summary, "pending_approval", "agent", f"request_id={request_id}")
    return {"status": "approval_required", "request_id": request_id,
            "message": "Action suspendue : approbation humaine requise avant exécution."}


def dispatch(tool, arguments, executor):
    if tool not in VALID_TOOLS:
        raise ValueError("Outil non reconnu.")
    config = get_config()
    profile = config["profile"]
    summary = _summary(arguments)
    allowed = "*" in PROFILES[profile] or tool in PROFILES[profile]
    if not allowed:
        _audit("tool_call", tool, summary, "denied", "agent", "Outil absent du profil actif")
        return {"error": f"Action refusée par le profil {profile}."}
    if tool in SENSITIVE_TOOLS:
        return _request(tool, arguments, summary)
    try:
        result = executor(tool, arguments)
        _audit("tool_call", tool, summary, "allowed", "agent", str(result)[:1000])
        return result
    except Exception as exc:
        _audit("tool_call", tool, summary, "error", "agent", str(exc)[:1000])
        raise


def list_requests(limit=50):
    with db.connect() as conn:
        conn.execute("""UPDATE permission_requests SET status='expired'
            WHERE status='pending' AND expires_at <= ?""", (_now(),))
        rows = conn.execute("SELECT id,tool,arguments_summary,status,expires_at,created_at,decided_at,result_summary FROM permission_requests ORDER BY id DESC LIMIT ?",
                            (max(1, min(int(limit), 200)),)).fetchall()
    return [dict(row) for row in rows]


def decide(request_id, approve, executor, actor="user"):
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM permission_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise KeyError("Demande d'approbation introuvable.")
        if row["status"] != "pending":
            raise ValueError("Cette demande n'est plus en attente.")
        if row["expires_at"] <= _now():
            conn.execute("UPDATE permission_requests SET status='expired',decided_at=CURRENT_TIMESTAMP WHERE id=?", (request_id,))
            expired = True
        else:
            expired = False
            tool, arguments, summary = row["tool"], json.loads(row["arguments_json"]), row["arguments_summary"]
            conn.execute("UPDATE permission_requests SET status=? ,decided_at=CURRENT_TIMESTAMP WHERE id=?",
                         ("approved" if approve else "denied", request_id))
    if expired:
        raise ValueError("Cette demande a expiré.")
    if not approve:
        _audit("approval_decision", tool, summary, "denied", actor, "Refus humain")
        return {"id": request_id, "status": "denied"}
    config = get_config()
    if "*" not in PROFILES[config["profile"]] and tool not in PROFILES[config["profile"]]:
        with db.connect() as conn:
            conn.execute("UPDATE permission_requests SET status='denied',result_summary=? WHERE id=?",
                         ("Profil modifié avant exécution", request_id))
        _audit("approval_execution", tool, summary, "denied", actor, "Profil modifié avant exécution")
        raise PermissionError("Le profil actif n'autorise plus cette action.")
    try:
        result = executor(tool, arguments)
        result_summary = str(result)[:1000]
        status = "executed"
        _audit("approval_execution", tool, summary, "executed", actor, result_summary)
    except Exception as exc:
        result_summary = str(exc)[:1000]
        status = "failed"
        _audit("approval_execution", tool, summary, "failed", actor, result_summary)
        raise
    finally:
        with db.connect() as conn:
            conn.execute("UPDATE permission_requests SET status=?,result_summary=? WHERE id=?",
                         (status if "status" in locals() else "failed",
                          result_summary if "result_summary" in locals() else "Échec", request_id))
    return {"id": request_id, "status": status, "result": result}


def list_audit(limit=100):
    with db.connect() as conn:
        rows = conn.execute("""SELECT id,event,tool,arguments_summary,decision,actor,result_summary,created_at
            FROM permission_audit ORDER BY id DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),)).fetchall()
    return [dict(row) for row in rows]
