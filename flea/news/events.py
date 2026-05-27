from sqlite3 import Connection

from flea.news.sources import Article


def article_exists(conn: Connection, url: str) -> bool:
    cur = conn.execute("SELECT 1 FROM news_articles WHERE url = ?", (url,))
    return cur.fetchone() is not None


def store_article(conn: Connection, article: Article, fetched_at: int) -> None:
    conn.execute(
        """
        INSERT INTO news_articles (url, source, title, published_at, fetched_at, body)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            article.url,
            article.source,
            article.title,
            article.published_at,
            fetched_at,
            article.body,
        ),
    )


def resolve_item(conn: Connection, name: str) -> str | None:
    """Best-effort map a free-text item name to an item id from the catalog."""
    if not name:
        return None
    cleaned = name.strip()
    cur = conn.execute(
        "SELECT id FROM items WHERE LOWER(short_name) = LOWER(?) LIMIT 1",
        (cleaned,),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "SELECT id FROM items WHERE LOWER(name) = LOWER(?) LIMIT 1",
        (cleaned,),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "SELECT id FROM items WHERE LOWER(name) LIKE LOWER(?) LIMIT 1",
        (f"%{cleaned}%",),
    )
    row = cur.fetchone()
    return row["id"] if row else None


def store_event(conn: Connection, article_url: str, event: dict, created_at: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO events (
            article_url, event_type, direction, confidence,
            time_horizon, summary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            article_url,
            event["event_type"],
            event["direction"],
            event["confidence"],
            event["time_horizon"],
            event["summary"],
            created_at,
        ),
    )
    event_id = cur.lastrowid

    for item_name in event.get("affected_items", []):
        item_id = resolve_item(conn, item_name)
        if item_id:
            conn.execute(
                "INSERT OR IGNORE INTO event_items (event_id, item_id) VALUES (?, ?)",
                (event_id, item_id),
            )

    return event_id
