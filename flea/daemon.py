import logging
import signal
import threading
import time
from logging.handlers import RotatingFileHandler

from flea.config import Config
from flea.fetcher import fetch_and_store
from flea.llm import make_llm_client
from flea.news.events import article_exists, store_article, store_event
from flea.news.extractor import Extractor
from flea.news.sources import RedditSource
from flea.signals import (
    crash_signals,
    dip_buy_signals,
    store_signals,
    vendor_flip_signals,
)
from flea.storage import connect, init_db

log = logging.getLogger("flea.daemon")


def _setup_logging(cfg: Config) -> None:
    cfg.log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return

    fh = RotatingFileHandler(cfg.log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _build_news_sources(cfg: Config) -> list:
    sources = []
    enabled = cfg.news_sources or {}
    if enabled.get("reddit", True):
        sources.append(RedditSource())
    return sources


def _price_cycle(cfg: Config) -> None:
    log.info("price cycle: fetching tarkov.dev")
    items, snaps = fetch_and_store(cfg)
    log.info("price cycle: items=%d snapshots=%d", items, snaps)

    now = int(time.time())
    with connect(cfg.db_path) as conn:
        vf = vendor_flip_signals(conn, limit=50)
        db = dip_buy_signals(conn, cfg, limit=50)
        cr = crash_signals(conn, limit=50)
        total = store_signals(conn, vf + db + cr, created_at=now)
        conn.commit()
    log.info(
        "price cycle: signals stored=%d (vendor_flip=%d dip_buy=%d crash=%d)",
        total, len(vf), len(db), len(cr),
    )


def _news_cycle(cfg: Config) -> None:
    sources = _build_news_sources(cfg)
    if not sources:
        log.info("news cycle: no sources enabled")
        return

    llm = make_llm_client(cfg)
    extractor = Extractor(llm)
    now = int(time.time())
    new_articles = 0
    total_events = 0

    with connect(cfg.db_path) as conn:
        for src in sources:
            try:
                articles = src.fetch()
            except Exception:
                log.exception("news cycle: source %s failed", src.name)
                continue
            log.info("news cycle: %s returned %d articles", src.name, len(articles))

            for art in articles:
                if article_exists(conn, art.url):
                    continue
                try:
                    events = extractor.extract(art)
                except Exception as e:
                    body = getattr(getattr(e, "response", None), "text", None)
                    log.error(
                        "news cycle: extraction failed for %s: %s%s",
                        art.url,
                        e,
                        f" | body={body}" if body else "",
                    )
                    continue
                store_article(conn, art, fetched_at=now)
                new_articles += 1
                for ev in events:
                    store_event(conn, art.url, ev, created_at=now)
                    total_events += 1
                if events:
                    log.info("news cycle: + %s (%d events)", art.title[:80], len(events))
            conn.commit()

    log.info("news cycle: new_articles=%d events=%d", new_articles, total_events)


def _loop(
    name: str,
    interval: int,
    fn,
    cfg: Config,
    stop: threading.Event,
) -> None:
    log.info("%s loop started (interval=%ds)", name, interval)
    while not stop.is_set():
        cycle_start = time.monotonic()
        try:
            fn(cfg)
        except Exception:
            log.exception("%s cycle raised", name)
        elapsed = time.monotonic() - cycle_start
        wait = max(0.0, interval - elapsed)
        log.info("%s loop sleeping %.1fs (cycle took %.1fs)", name, wait, elapsed)
        if stop.wait(wait):
            break
    log.info("%s loop stopped", name)


def run(cfg: Config) -> None:
    _setup_logging(cfg)
    init_db(cfg.db_path)
    log.info("daemon starting (db=%s)", cfg.db_path)

    stop = threading.Event()

    def _on_signal(signum, _frame):
        log.info("received signal %d, shutting down", signum)
        stop.set()

    signal.signal(signal.SIGINT, _on_signal)
    try:
        signal.signal(signal.SIGTERM, _on_signal)
    except (AttributeError, ValueError):
        pass

    threads = [
        threading.Thread(
            target=_loop,
            name="price",
            args=("price", cfg.price_interval_seconds, _price_cycle, cfg, stop),
            daemon=True,
        ),
        threading.Thread(
            target=_loop,
            name="news",
            args=("news", cfg.news_interval_seconds, _news_cycle, cfg, stop),
            daemon=True,
        ),
    ]
    for t in threads:
        t.start()

    try:
        while not stop.is_set():
            stop.wait(1.0)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=10)
        log.info("daemon stopped")
