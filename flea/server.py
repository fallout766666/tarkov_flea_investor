import time
from contextlib import contextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from flea.config import Config, load_config
from flea.storage import connect


def _require_api_key(cfg: Config):
    def _dep(x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or x_api_key != cfg.flea_api_key:
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    return _dep


def _ip_allowlist_middleware(allowed: list[str]):
    allowed_set = set(allowed)

    async def middleware(request: Request, call_next):
        if allowed_set:
            client_host = request.client.host if request.client else None
            if client_host not in allowed_set:
                return JSONResponse({"detail": "forbidden"}, status_code=403)
        return await call_next(request)

    return middleware


@contextmanager
def _db(cfg: Config):
    conn = connect(cfg.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


def create_app(cfg: Config) -> FastAPI:
    if not cfg.flea_api_key:
        raise RuntimeError(
            "FLEA_API_KEY is not set in .env — refusing to start an unauthenticated server."
        )

    app = FastAPI(title="tarkov-flea-investor", version="0.1.0")
    app.middleware("http")(_ip_allowlist_middleware(cfg.server_allowed_ips))
    auth = Depends(_require_api_key(cfg))

    @app.get("/health")
    def health():
        with _db(cfg) as conn:
            last_snap = conn.execute(
                "SELECT MAX(captured_at) AS t FROM price_snapshots"
            ).fetchone()
            last_article = conn.execute(
                "SELECT MAX(fetched_at) AS t FROM news_articles"
            ).fetchone()
            last_signal = conn.execute(
                "SELECT MAX(created_at) AS t FROM signals"
            ).fetchone()
        now = int(time.time())
        return {
            "now": now,
            "last_price_snapshot": last_snap["t"],
            "last_news_fetch": last_article["t"],
            "last_signal_emit": last_signal["t"],
            "price_stale_seconds": (now - last_snap["t"]) if last_snap["t"] else None,
            "news_stale_seconds": (now - last_article["t"]) if last_article["t"] else None,
        }

    @app.get("/signals", dependencies=[auth])
    def signals(type: str | None = None, limit: int = 50):
        limit = max(1, min(limit, 500))
        with _db(cfg) as conn:
            latest_ts = conn.execute(
                "SELECT MAX(created_at) AS t FROM signals"
            ).fetchone()["t"]
            if latest_ts is None:
                return {"latest_emit": None, "signals": []}

            sql = """
                SELECT s.item_id, s.signal_type, s.action, s.score, s.reasoning,
                       s.created_at, i.name, i.short_name
                FROM signals s
                JOIN items i ON i.id = s.item_id
                WHERE s.created_at = ?
            """
            params: list = [latest_ts]
            if type:
                sql += " AND s.signal_type = ?"
                params.append(type)
            sql += " ORDER BY s.score DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        return {
            "latest_emit": latest_ts,
            "signals": [_row_to_dict(r) for r in rows],
        }

    @app.get("/events", dependencies=[auth])
    def events(min_confidence: float = 0.0, limit: int = 50):
        limit = max(1, min(limit, 500))
        with _db(cfg) as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.event_type, e.direction, e.confidence,
                       e.time_horizon, e.summary, e.created_at,
                       a.title AS article_title, a.source AS article_source,
                       a.url   AS article_url
                FROM events e
                LEFT JOIN news_articles a ON a.url = e.article_url
                WHERE e.confidence >= ?
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT ?
                """,
                (min_confidence, limit),
            ).fetchall()
            out = []
            for row in rows:
                items = conn.execute(
                    """
                    SELECT i.id, i.name, i.short_name
                    FROM event_items ei
                    JOIN items i ON i.id = ei.item_id
                    WHERE ei.event_id = ?
                    """,
                    (row["id"],),
                ).fetchall()
                d = _row_to_dict(row)
                d["items"] = [_row_to_dict(it) for it in items]
                out.append(d)
        return {"events": out}

    @app.get("/items", dependencies=[auth])
    def items(q: str | None = None, limit: int = 20):
        limit = max(1, min(limit, 100))
        with _db(cfg) as conn:
            if q:
                like = f"%{q}%"
                rows = conn.execute(
                    """
                    SELECT id, name, short_name, base_price
                    FROM items
                    WHERE name LIKE ? COLLATE NOCASE
                       OR short_name LIKE ? COLLATE NOCASE
                    ORDER BY length(name)
                    LIMIT ?
                    """,
                    (like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, short_name, base_price FROM items ORDER BY name LIMIT ?",
                    (limit,),
                ).fetchall()
        return {"items": [_row_to_dict(r) for r in rows]}

    @app.get("/items/{item_id}/history", dependencies=[auth])
    def history(item_id: str, window: str = "7d"):
        windows = {
            "24h": 24 * 3600,
            "7d": 7 * 24 * 3600,
            "30d": 30 * 24 * 3600,
        }
        if window not in windows:
            raise HTTPException(status_code=400, detail=f"window must be one of {list(windows)}")
        since = int(time.time()) - windows[window]
        with _db(cfg) as conn:
            item = conn.execute(
                "SELECT id, name, short_name, base_price FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not item:
                raise HTTPException(status_code=404, detail="item not found")
            rows = conn.execute(
                """
                SELECT captured_at, last_low_price, avg_24h_price,
                       change_last_48h_pct, best_trader_name, best_trader_price
                FROM price_snapshots
                WHERE item_id = ? AND captured_at >= ?
                ORDER BY captured_at ASC
                """,
                (item_id, since),
            ).fetchall()
        return {
            "item": _row_to_dict(item),
            "window": window,
            "snapshots": [_row_to_dict(r) for r in rows],
        }

    return app


def run(cfg: Config) -> None:
    import uvicorn

    app = create_app(cfg)
    uvicorn.run(app, host=cfg.server_host, port=cfg.server_port, log_level="info")
