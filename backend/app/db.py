import json
import sqlite3
from .config import DATA

DB = DATA / "automaton.db"

def connect():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def init():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS memories(
            id INTEGER PRIMARY KEY, content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
            importance INTEGER NOT NULL DEFAULT 3 CHECK(importance BETWEEN 1 AND 5),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS heartbeat_config(
            id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
            interval_seconds INTEGER NOT NULL DEFAULT 1800,
            prompt TEXT NOT NULL DEFAULT 'Vérifie les tâches planifiées et l’état du workspace. N’effectue aucune action destructive.')""")
        c.execute("""INSERT OR IGNORE INTO heartbeat_config(id) VALUES(1)""")
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY, prompt TEXT NOT NULL, status TEXT NOT NULL
                CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
            result TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME, finished_at DATETIME)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_id ON tasks(status, id)")
        # A process may have exited while a task was running. Requeue it on startup.
        c.execute("""UPDATE tasks SET status='queued', updated_at=CURRENT_TIMESTAMP,
                     started_at=NULL, finished_at=NULL,
                     error='Reprise après arrêt du backend.'
                     WHERE status='running'""")

        c.execute("""CREATE TABLE IF NOT EXISTS objectives(
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','failed','cancelled')),
            priority INTEGER NOT NULL DEFAULT 3 CHECK(priority BETWEEN 1 AND 5),
            due_at TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, completed_at DATETIME)""")
        c.execute("""CREATE TABLE IF NOT EXISTS objective_steps(
            id INTEGER PRIMARY KEY, objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
            position INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','queued','running','succeeded','failed','skipped')),
            task_id INTEGER REFERENCES tasks(id), result TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '', created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(objective_id, position))""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_objective_steps_status ON objective_steps(objective_id,status,position)")

        columns = {row["name"] for row in c.execute("PRAGMA table_info(objectives)").fetchall()}
        if "supervisor_state" not in columns:
            c.execute("ALTER TABLE objectives ADD COLUMN supervisor_state TEXT NOT NULL DEFAULT 'monitoring'")
        if "supervisor_note" not in columns:
            c.execute("ALTER TABLE objectives ADD COLUMN supervisor_note TEXT NOT NULL DEFAULT ''")
        if "supervised_at" not in columns:
            c.execute("ALTER TABLE objectives ADD COLUMN supervised_at DATETIME")
        c.execute("""CREATE TABLE IF NOT EXISTS objective_events(
            id INTEGER PRIMARY KEY, objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL, message TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS objective_revisions(
            id INTEGER PRIMARY KEY, objective_id INTEGER NOT NULL REFERENCES objectives(id) ON DELETE CASCADE,
            revision INTEGER NOT NULL, reason TEXT NOT NULL, plan_json TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(objective_id,revision))""")
        legacy_objectives=c.execute("""SELECT id FROM objectives
            WHERE NOT EXISTS (SELECT 1 FROM objective_revisions r WHERE r.objective_id=objectives.id)""").fetchall()
        for legacy in legacy_objectives:
            legacy_steps=c.execute("SELECT title,description FROM objective_steps WHERE objective_id=? ORDER BY position",
                                   (legacy["id"],)).fetchall()
            snapshot=[{"title":row["title"],"description":row["description"]} for row in legacy_steps]
            c.execute("INSERT INTO objective_revisions(objective_id,revision,reason,plan_json) VALUES(?,1,?,?)",
                      (legacy["id"],"Plan existant archivé lors de la migration",json.dumps(snapshot,ensure_ascii=False)))



        c.execute("""CREATE TABLE IF NOT EXISTS heartbeat_runs(
            id INTEGER PRIMARY KEY, status TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '', started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME)""")
        c.execute("""CREATE TABLE IF NOT EXISTS verification_runs(
            id INTEGER PRIMARY KEY, checks_json TEXT NOT NULL, result_json TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")

def save(role, content):
    with connect() as c:
        c.execute("INSERT INTO messages(role,content) VALUES(?,?)", (role, content))

def history(limit=20):
    with connect() as c:
        rows = c.execute("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

def add_memory(content, tags="", importance=3):
    with connect() as c:
        cur = c.execute("INSERT INTO memories(content,tags,importance) VALUES(?,?,?)",
                        (content, tags, importance))
        return cur.lastrowid

def search_memories(query="", limit=20):
    query = f"%{query.strip()}%"
    with connect() as c:
        rows = c.execute("""SELECT id,content,tags,importance,created_at,updated_at
            FROM memories WHERE content LIKE ? OR tags LIKE ?
            ORDER BY importance DESC, updated_at DESC LIMIT ?""",
            (query, query, max(1, min(limit, 100)))).fetchall()
    return [dict(r) for r in rows]

def delete_memory(memory_id):
    with connect() as c:
        cur = c.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        return cur.rowcount > 0

def get_heartbeat():
    with connect() as c:
        return dict(c.execute("SELECT * FROM heartbeat_config WHERE id=1").fetchone())

def set_heartbeat(enabled=None, interval_seconds=None, prompt=None):
    current = get_heartbeat()
    with connect() as c:
        c.execute("""UPDATE heartbeat_config SET enabled=?, interval_seconds=?, prompt=? WHERE id=1""",
                  (int(current["enabled"] if enabled is None else enabled),
                   current["interval_seconds"] if interval_seconds is None else interval_seconds,
                   current["prompt"] if prompt is None else prompt))
    return get_heartbeat()

def record_heartbeat(status, summary="", error=""):
    with connect() as c:
        c.execute("""INSERT INTO heartbeat_runs(status,summary,error,finished_at)
                     VALUES(?,?,?,CURRENT_TIMESTAMP)""", (status, summary[:4000], error[:2000]))

def heartbeat_history(limit=20):
    with connect() as c:
        rows = c.execute("SELECT * FROM heartbeat_runs ORDER BY id DESC LIMIT ?",
                         (max(1, min(limit, 100)),)).fetchall()
    return [dict(r) for r in rows]


def create_task(prompt):
    with connect() as c:
        cur = c.execute("INSERT INTO tasks(prompt,status) VALUES(?, 'queued')", (prompt,))
        row = c.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)

def list_tasks(limit=50):
    with connect() as c:
        rows = c.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?",
                         (max(1, min(limit, 200)),)).fetchall()
    return [dict(row) for row in rows]

def get_task(task_id):
    with connect() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None

def claim_task():
    # BEGIN IMMEDIATE prevents two local workers from claiming the same row.
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT id,prompt FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        cur = c.execute("""UPDATE tasks SET status='running', started_at=CURRENT_TIMESTAMP,
                           updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'""", (row["id"],))
        if cur.rowcount != 1:
            return None
        return {"id": row["id"], "prompt": row["prompt"]}

def finish_task(task_id, status, result="", error=""):
    if status not in {"queued", "succeeded", "failed"}:
        raise ValueError("Invalid task status")
    with connect() as c:
        c.execute("""UPDATE tasks SET status=?, result=?, error=?, updated_at=CURRENT_TIMESTAMP,
                     started_at=CASE WHEN ?='queued' THEN NULL ELSE started_at END,
                     finished_at=CASE WHEN ? IN ('succeeded','failed') THEN CURRENT_TIMESTAMP ELSE NULL END
                     WHERE id=?""", (status, result[:12000], error[:4000], status, status, task_id))

def cancel_task(task_id):
    with connect() as c:
        cur = c.execute("""UPDATE tasks SET status='cancelled', updated_at=CURRENT_TIMESTAMP,
                           finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'""", (task_id,))
        return cur.rowcount > 0


def create_objective(title, description, steps, priority=3, due_at=None):
    with connect() as c:
        cur = c.execute("INSERT INTO objectives(title,description,priority,due_at) VALUES(?,?,?,?)",
                        (title, description, priority, due_at))
        objective_id = cur.lastrowid
        for position, step in enumerate(steps, 1):
            c.execute("""INSERT INTO objective_steps(objective_id,position,title,description)
                         VALUES(?,?,?,?)""", (objective_id, position, step["title"], step["description"]))
    snapshot = [{"title": step["title"], "description": step["description"]} for step in steps]
    with connect() as c:
        c.execute("INSERT INTO objective_revisions(objective_id,revision,reason,plan_json) VALUES(?,1,'Plan initial',?)",
                  (objective_id, json.dumps(snapshot, ensure_ascii=False)))
        c.execute("INSERT INTO objective_events(objective_id,event_type,message) VALUES(?,?,?)",
                  (objective_id,"created","Objectif créé et plan initial enregistré."))
    return get_objective(objective_id)

def list_objectives(limit=50):
    with connect() as c:
        rows = c.execute("""SELECT o.*, COUNT(s.id) AS total_steps,
            SUM(CASE WHEN s.status IN ('succeeded','skipped') THEN 1 ELSE 0 END) AS completed_steps
            FROM objectives o LEFT JOIN objective_steps s ON s.objective_id=o.id
            GROUP BY o.id ORDER BY CASE o.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
            o.priority DESC,o.id DESC LIMIT ?""", (max(1,min(limit,100)),)).fetchall()
    return [dict(r) for r in rows]

def get_objective(objective_id):
    with connect() as c:
        row=c.execute("SELECT * FROM objectives WHERE id=?",(objective_id,)).fetchone()
        if row is None: return None
        steps=c.execute("SELECT * FROM objective_steps WHERE objective_id=? ORDER BY position",(objective_id,)).fetchall()
    result=dict(row); result["steps"]=[dict(s) for s in steps]
    result["total_steps"]=len(steps)
    result["completed_steps"]=sum(1 for s in steps if s["status"]=="succeeded")
    return result

def queue_objective_step(objective_id, step_id):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        obj=c.execute("SELECT status FROM objectives WHERE id=?",(objective_id,)).fetchone()
        step=c.execute("SELECT * FROM objective_steps WHERE id=? AND objective_id=?",(step_id,objective_id)).fetchone()
        if not obj or obj["status"]!="active" or not step or step["status"] not in ("pending","failed"):
            return False
        cur=c.execute("INSERT INTO tasks(prompt,status) VALUES(?, 'queued')",
                      (step["title"]+"\n\n"+step["description"],))
        c.execute("""UPDATE objective_steps SET status='queued',task_id=?,error='',
                     updated_at=CURRENT_TIMESTAMP WHERE id=?""",(cur.lastrowid,step_id))
        c.execute("UPDATE objectives SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(objective_id,))
        return True

def reconcile_objective_task(task_id, status, result="", error=""):
    with connect() as c:
        step=c.execute("SELECT id,objective_id FROM objective_steps WHERE task_id=?",(task_id,)).fetchone()
        if not step: return
        mapped={"running":"running","succeeded":"succeeded","failed":"failed","queued":"pending"}
        step_status=mapped.get(status)
        if not step_status: return
        c.execute("""UPDATE objective_steps SET status=?,result=?,error=?,updated_at=CURRENT_TIMESTAMP
                     WHERE id=?""",(step_status,result[:12000],error[:4000],step["id"]))
        c.execute("UPDATE objectives SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(step["objective_id"],))
        remaining=c.execute("""SELECT COUNT(*) FROM objective_steps WHERE objective_id=?
                               AND status NOT IN ('succeeded','skipped')""",(step["objective_id"],)).fetchone()[0]
        failed=c.execute("SELECT COUNT(*) FROM objective_steps WHERE objective_id=? AND status='failed'",
                         (step["objective_id"],)).fetchone()[0]
        objective_status=c.execute("SELECT status FROM objectives WHERE id=?",(step["objective_id"],)).fetchone()
        if failed:
            c.execute("UPDATE objectives SET status='active',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'",
                      (step["objective_id"],))

def set_objective_status(objective_id, status):
    if status not in {"active","paused","cancelled"}: raise ValueError("Statut invalide")
    with connect() as c:
        current=c.execute("SELECT status FROM objectives WHERE id=?",(objective_id,)).fetchone()
        if current is None or current["status"] in ("completed","cancelled"): return False
        if status in ("paused","cancelled"):
            queued=c.execute("SELECT id,task_id FROM objective_steps WHERE objective_id=? AND status='queued'",
                             (objective_id,)).fetchall()
            for step in queued:
                if step["task_id"] is not None:
                    c.execute("""UPDATE tasks SET status='cancelled',updated_at=CURRENT_TIMESTAMP,
                                  finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'""",(step["task_id"],))
                next_status="pending" if status=="paused" else "skipped"
                c.execute("""UPDATE objective_steps SET status=?,task_id=NULL,updated_at=CURRENT_TIMESTAMP
                             WHERE id=?""",(next_status,step["id"]))
        c.execute("""UPDATE objectives SET status=?,supervisor_state=CASE WHEN ?='active' THEN 'monitoring' ELSE supervisor_state END,
                     updated_at=CURRENT_TIMESTAMP WHERE id=?""",(status,status,objective_id))
        return True

def retry_objective_step(objective_id, step_id):
    with connect() as c:
        cur=c.execute("""UPDATE objective_steps SET status='pending',task_id=NULL,error='',
                         updated_at=CURRENT_TIMESTAMP WHERE id=? AND objective_id=? AND status='failed'""",
                      (step_id,objective_id))
        if cur.rowcount: c.execute("UPDATE objectives SET status='active',supervisor_state='monitoring',updated_at=CURRENT_TIMESTAMP WHERE id=?",(objective_id,))
        return cur.rowcount > 0

def objective_supervision_candidates(interval_seconds=60):
    with connect() as c:
        rows=c.execute("""SELECT o.id FROM objectives o
            WHERE o.status='active' AND o.supervisor_state!='blocked'
            AND (o.supervised_at IS NULL OR o.supervised_at <= datetime('now', ?))
            AND NOT EXISTS (SELECT 1 FROM objective_steps s WHERE s.objective_id=o.id
                            AND s.status IN ('queued','running'))
            ORDER BY o.priority DESC,o.id""",(f"-{max(30,min(interval_seconds,86400))} seconds",)).fetchall()
    return [row["id"] for row in rows]

def record_supervision(objective_id, decision, note, new_steps=None):
    new_steps=new_steps or []
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        obj=c.execute("SELECT status FROM objectives WHERE id=?",(objective_id,)).fetchone()
        if not obj or obj["status"]!="active": return False
        rows=c.execute("SELECT * FROM objective_steps WHERE objective_id=? ORDER BY position",(objective_id,)).fetchall()
        if any(row["status"] in ("queued","running") for row in rows): return False
        current_revision=c.execute("SELECT COALESCE(MAX(revision),0) FROM objective_revisions WHERE objective_id=?",(objective_id,)).fetchone()[0]
        if new_steps:
            if len(rows)+len(new_steps)>20: 
                decision="blocked"
                note=(note+" Limite de 20 étapes atteinte; plan non modifié.")[:2000]
                new_steps=[]
            elif decision=="replan":
                failed=[row for row in rows if row["status"]=="failed"]
                if failed:
                    failed_position=min(row["position"] for row in failed)
                    for row in failed:
                        c.execute("""UPDATE objective_steps SET status='skipped',updated_at=CURRENT_TIMESTAMP
                                     WHERE id=?""",(row["id"],))
                    c.execute("UPDATE objective_steps SET position=position+1000 WHERE objective_id=? AND position>?",
                              (objective_id,failed_position))
                    c.execute("UPDATE objective_steps SET position=position-1000+? WHERE objective_id=? AND position>=1000",
                              (len(new_steps),objective_id))
                    insert_position=failed_position+1
                else:
                    insert_position=len(rows)+1
                for offset,step in enumerate(new_steps):
                    c.execute("""INSERT INTO objective_steps(objective_id,position,title,description)
                                 VALUES(?,?,?,?)""",(objective_id,insert_position+offset,step["title"],step["description"]))
                rows=c.execute("SELECT * FROM objective_steps WHERE objective_id=? ORDER BY position",(objective_id,)).fetchall()
                snapshot=[{"title":row["title"],"description":row["description"]} for row in rows]
                c.execute("INSERT INTO objective_revisions(objective_id,revision,reason,plan_json) VALUES(?,?,?,?)",
                          (objective_id,current_revision+1,"Adaptation supervisée",json.dumps(snapshot,ensure_ascii=False)))
                c.execute("INSERT INTO objective_events(objective_id,event_type,message,details) VALUES(?,?,?,?)",
                          (objective_id,"replanned",note,json.dumps({"added_steps":new_steps},ensure_ascii=False)))
        if decision=="blocked":
            state="blocked"
        else:
            state="monitoring"
        if decision=="completed":
            remaining=c.execute("SELECT COUNT(*) FROM objective_steps WHERE objective_id=? AND status NOT IN ('succeeded','skipped')",
                                (objective_id,)).fetchone()[0]
            if remaining:
                decision="blocked"; state="blocked"
                note=(note+" Le superviseur refuse de clôturer: des étapes ne sont pas réussies.")[:2000]
            else:
                c.execute("UPDATE objectives SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=?",(objective_id,))
        c.execute("""UPDATE objectives SET supervisor_state=?,supervisor_note=?,
                     supervised_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                  (state,note[:2000],objective_id))
        c.execute("INSERT INTO objective_events(objective_id,event_type,message) VALUES(?,?,?)",
                  (objective_id,"supervision_"+decision,note[:2000]))
        return True

def record_supervision_error(objective_id, error):
    with connect() as c:
        c.execute("""UPDATE objectives SET supervisor_note=?,supervised_at=CURRENT_TIMESTAMP,
                     updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'""",
                  (("Erreur de supervision : "+str(error))[:2000],objective_id))
        c.execute("INSERT INTO objective_events(objective_id,event_type,message) VALUES(?,?,?)",
                  (objective_id,"supervision_error",str(error)[:2000]))

def objective_history(objective_id):
    with connect() as c:
        events=c.execute("SELECT * FROM objective_events WHERE objective_id=? ORDER BY id DESC LIMIT 100",(objective_id,)).fetchall()
        revisions=c.execute("SELECT id,revision,reason,plan_json,created_at FROM objective_revisions WHERE objective_id=? ORDER BY revision DESC",(objective_id,)).fetchall()
    return {"events":[dict(row) for row in events],"revisions":[dict(row) for row in revisions]}



def record_verification_run(checks, result):
    with connect() as c:
        cur=c.execute("INSERT INTO verification_runs(checks_json,result_json) VALUES(?,?)",
                      (json.dumps(checks,ensure_ascii=False),json.dumps(result,ensure_ascii=False)))
        return cur.lastrowid


def list_verification_runs(limit=20):
    with connect() as c:
        rows=c.execute("SELECT * FROM verification_runs ORDER BY id DESC LIMIT ?",
                       (max(1,min(limit,100)),)).fetchall()
    return [{"id":row["id"],"checks":json.loads(row["checks_json"]),
             "result":json.loads(row["result_json"]),"created_at":row["created_at"]} for row in rows]
