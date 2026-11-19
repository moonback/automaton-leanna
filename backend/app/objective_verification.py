"""Persist and enforce deterministic acceptance checks for objective steps."""
import json

from . import db, verification as workspace_verification


ALLOWED = {"exists", "contains", "python_syntax"}


def ensure_schema():
    with db.connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS objective_step_verification (
            step_id INTEGER PRIMARY KEY REFERENCES objective_steps(id) ON DELETE CASCADE,
            checks_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            verified_at DATETIME
        )""")


def normalize_checks(checks):
    if not isinstance(checks, list) or not 1 <= len(checks) <= 10:
        raise ValueError("Chaque étape exige entre 1 et 10 critères de vérification.")
    normalized = []
    for check in checks:
        if not isinstance(check, dict) or check.get("kind") not in ALLOWED:
            raise ValueError("Critère invalide : seuls exists, contains et python_syntax sont autorisés.")
        path = check.get("path")
        if not isinstance(path, str) or not path.strip() or path.startswith(("/", "\\")):
            raise ValueError("Chaque critère doit cibler un chemin relatif du workspace.")
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
        rows = conn.execute("SELECT id,position FROM objective_steps WHERE objective_id=? ORDER BY position",
                            (objective_id,)).fetchall()
        by_title = {(item["title"], item["description"]): item for item in steps}
        for row in rows:
            existing = conn.execute("SELECT 1 FROM objective_step_verification WHERE step_id=?", (row["id"],)).fetchone()
            if existing:
                continue
            candidate = by_title.get((row["title"], row["description"]))
            if candidate:
                conn.execute("INSERT INTO objective_step_verification(step_id,checks_json) VALUES(?,?)",
                             (row["id"], json.dumps(candidate["checks"], ensure_ascii=False)))


def verify_task(task_id, agent_result):
    ensure_schema()
    with db.connect() as conn:
        row = conn.execute("""SELECT s.id, s.objective_id, v.checks_json
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
