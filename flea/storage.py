import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT,
    base_price INTEGER,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    item_id TEXT NOT NULL,
    captured_at INTEGER NOT NULL,
    last_low_price INTEGER,
    avg_24h_price INTEGER,
    change_last_48h_pct REAL,
    best_trader_name TEXT,
    best_trader_price INTEGER,
    PRIMARY KEY (item_id, captured_at),
    FOREIGN KEY (item_id) REFERENCES items(id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_item_time
    ON price_snapshots (item_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS news_articles (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT,
    published_at INTEGER,
    fetched_at INTEGER NOT NULL,
    body TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_url TEXT,
    event_type TEXT NOT NULL,
    direction TEXT,
    confidence REAL,
    time_horizon TEXT,
    summary TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (article_url) REFERENCES news_articles(url)
);

CREATE TABLE IF NOT EXISTS event_items (
    event_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (event_id, item_id),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    action TEXT NOT NULL,
    score REAL,
    reasoning TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (item_id) REFERENCES items(id)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        if not _column_exists(conn, "events", "summary"):
            conn.execute("ALTER TABLE events ADD COLUMN summary TEXT")
        conn.commit()
