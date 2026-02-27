import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("SQLITE_PATH", "data/comics.db")


def get_conn() -> sqlite3.Connection:
    # Longer timeout + WAL reduces "database is locked" during concurrent
    # background imports while the web app is reading.
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn
