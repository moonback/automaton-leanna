"""Persist and enforce deterministic acceptance checks for objective steps."""
import hashlib
import json
from pathlib import Path

from . import db, verification as workspace_verification
from .config import WORKSPACE


ALLOWED = {"exists", "contains", "python_syntax"}


def ensure_schema():
    with db.connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS objective_step_verification (
            step_id INTEGER PRIMARY KEY REFERENCES objective_steps(id) ON DELETE CASCADE,
            checks_json TEXT NOT NULL,
            baseline_json TEXT NOT NULL DEFAULT '{}',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            verified_at DATETIME
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(objective_step_verification)").fetchall()}
        if "baseline_json" not in columns:
            conn.execute("ALTER TABLE objective_step_verification ADD COLUMN baseline_json TEXT NOT NULL DEFAULT '{}'")


def normalize_checks(checks):
    if not isinstance(checks, list) or not 1 <= len(checks) <= 10:
        raise ValueError("Chaque étape exige entre 1 et 10 critères de vérification.")
    normalized = []
    for check in checks:
        if not isinstance(check, dict) or check.get("kind") not in ALLOWED:
            raise ValueError("Critère invalide : seuls exists, contains et python_syntax sont autorisés.")
        path = check.get("path")
        parts = path.replace("\\", "/").split("/") if isinstance(path, str) else []
        if not isinstance(path, str) or not path.strip() or path.startswith(("/", "\\")) or ":" in path or "\\x00" in path or ".." in parts:
            raise ValueError("Chaque critère doit cibler un chemin relatif sûr du workspace.")
        item = {"kind": check["kind"], "path": path}
        if check["kind"] == "contains":
            text = check.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("Le critère contains exige un texte attendu.")
            item["text"] = text[:1000]
        normalized.append(item)
    return normalized


def save_plan(objective_id, steps):
    ensure_schema()
    with db.connect() as conn:
        rows = conn.execute("SELECT id,position FROM objective_steps WHERE objective_id=? ORDER BY position",
                            (objective_id,)).fetchall()
        for row in rows:
            checks = steps[row["position"] - 1]["checks"]
            conn.execute("INSERT OR REPLACE INTO objective_step_verification(step_id,checks_json) VALUES(?,?)",
                         (row["id"], json.dumps(checks, ensure_ascii=False)))


def save_appended_plan(objective_id, steps):
    ensure_schema()
    with db.connect() as conn:
        rows = conn.execute("SELECT id,position,title,description FROM objective_steps WHERE objective_id=? ORDER BY position",
                            (objective_id,)).fetchall()
        unmatched = list(steps)
        for row in rows:
            existing = conn.execute("SELECT 1 FROM objective_step_verification WHERE step_id=?", (row["id"],)).fetchone()
            if existing:
                continue
            match = next((i for i, item in enumerate(unmatched)
                          if item["title"] == row["title"] and item["description"] == row["description"]), None)
            if match is not None:
                candidate = unmatched.pop(match)
                conn.execute("INSERT INTO objective_step_verification(step_id,checks_json) VALUES(?,?)",
                             (row["id"], json.dumps(candidate["checks"], ensure_ascii=False)))


def capture_baseline(step_id):
    ensure_schema()
    with db.connect() as conn:
        row = conn.execute("SELECT checks_json FROM objective_step_verification WHERE step_id=?", (step_id,)).fetchone()
    if row is None:
        raise ValueError("Critères d'acceptation absents pour cette étape.")
    root = WORKSPACE.resolve()
    baseline = {}
    for check in json.loads(row["checks_json"]):
        target = (root / check["path"]).resolve()
        if target != root and root not in target.parents:
            raise ValueError("Chemin de critère hors workspace.")
        digest = None
        if target.is_file() and target.stat().st_size <= workspace_verification.MAX_FILE_BYTES:
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
        baseline[check["path"]] = digest
    with db.connect() as conn:
        conn.execute("UPDATE objective_step_verification SET baseline_json=? WHERE step_id=?",
                     (json.dumps(baseline), step_id))


def verify_task(task_id, agent_result):
    ensure_schema()
    with db.connect() as conn:
        row = conn.execute("""SELECT s.id, s.objective_id, v.checks_json, v.baseline_json
            FROM objective_steps s LEFT JOIN objective_step_verification v ON v.step_id=s.id
            WHERE s.task_id=?""", (task_id,)).fetchone()
    if row is None:
        return None
    if not row["checks_json"]:
        evidence = {"success": False, "error": "Aucun critère d'acceptation enregistré : réussite refusée."}
    else:
        checks = json.loads(row["checks_json"])
        trace = (agent_result.get("tool_trace") or [])[-30:]
        mutations = [item for item in trace if item.get("success") and item.get("tool") in {"write_file", "run_python"}]
        evidence = workspace_verification.verify_workspace(checks)
        baseline = json.loads(row["baseline_json"] or "{}")
        for item in evidence["checks"]:
            before = baseline.get(item["path"])
            after = item.get("sha256")
            if before is not None and after == before:
                item["passed"] = False
                item["message"] += " Le fichier est identique à sa référence avant action."
        evidence["passed"] = sum(1 for item in evidence["checks"] if item["passed"])
        evidence["failed"] = len(evidence["checks"]) - evidence["passed"]
        evidence["success"] = evidence["failed"] == 0
        evidence["baseline_sha256"] = baseline
        evidence["tool_trace"] = trace
        evidence["agent_answer"] = str(agent_result.get("answer", ""))[:3000]
        evidence["action_confirmed"] = bool(mutations)
        if not mutations:
            evidence["success"] = False
            evidence["error"] = "Aucune action de production confirmée (write_file ou run_python)."
    with db.connect() as conn:
        conn.execute("""UPDATE objective_step_verification SET evidence_json=?, verified_at=CURRENT_TIMESTAMP
            WHERE step_id=?""", (json.dumps(evidence, ensure_ascii=False), row["id"]))
        conn.execute("""INSERT INTO objective_events(objective_id,event_type,message,details)
            VALUES(?,?,?,?)""", (row["objective_id"], "step_verification",
            "Vérification indépendante réussie." if evidence.get("success") else "Vérification indépendante échouée.",
            json.dumps({"step_id": row["id"], "evidence": evidence}, ensure_ascii=False)[:12000]))
    return evidence


def format_failure(evidence):
    if evidence.get("error"):
        return evidence["error"]
    failed = [item for item in evidence.get("checks", []) if not item.get("passed")]
    return "Critères non satisfaits : " + "; ".join(
        f"{item.get('path')}: {item.get('message')}" for item in failed
    )[:3500]
