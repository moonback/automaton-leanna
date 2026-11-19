import sqlite3
from .config import DATA
DB=DATA/"automaton.db"
def connect():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
def init():
 with connect() as c:c.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,role TEXT NOT NULL,content TEXT NOT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
def save(role,content):
 with connect() as c:c.execute("INSERT INTO messages(role,content) VALUES(?,?)",(role,content))
def history(limit=20):
 with connect() as c:rows=c.execute("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
 return [{"role":r["role"],"content":r["content"]} for r in reversed(rows)]
