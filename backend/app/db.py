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
        c.execute("""CREATE TABLE IF NOT EXISTS heartbeat_runs(
            id INTEGER PRIMARY KEY, status TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '', started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME)""")

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
                     finished_at=CASE WHEN ? IN ('succeeded','failed') THEN CURRENT_TIMESTAMP ELSE NULL END
                     WHERE id=?""", (status, result[:12000], error[:4000], status, task_id))

def cancel_task(task_id):
    with connect() as c:
        cur = c.execute("""UPDATE tasks SET status='cancelled', updated_at=CURRENT_TIMESTAMP,
                           finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'""", (task_id,))
        return cur.rowcount > 0
