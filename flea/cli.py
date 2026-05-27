import json
import time

import click

from flea import __version__
from flea.api import TarkovDevClient
from flea.config import load_config
from flea.fees import flea_listing_fee, flea_net_proceeds
from flea.fetcher import fetch_and_store
from flea.llm import make_llm_client
from flea.news.events import article_exists, store_article, store_event
from flea.news.extractor import Extractor
from flea.news.sources import RedditSource
from flea.signals import (
    Signal,
    crash_signals,
    dip_buy_signals,
    vendor_flip_signals,
)
from flea.storage import connect, init_db


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """Tarkov flea-market decision-support agent."""


@cli.command("init")
def init_cmd() -> None:
    """Initialize the local database."""
    cfg = load_config()
    init_db(cfg.db_path)
    click.echo(f"Initialized database at {cfg.db_path}")


@cli.group("db")
def db_grp() -> None:
    """Database maintenance."""


@db_grp.command("reset")
@click.option("--yes", is_flag=True,
              help="Skip the first confirmation. The typed-path confirmation is still required.")
def db_reset_cmd(yes: bool) -> None:
    """Delete all collected data. Two confirmations required."""
    cfg = load_config()
    if not cfg.db_path.exists():
        click.echo(f"No database at {cfg.db_path}; nothing to delete.")
        return

    size_kb = cfg.db_path.stat().st_size // 1024
    click.echo(f"This will permanently delete {cfg.db_path} ({size_kb} KB).")
    click.echo("All price history, news articles, events, and signals will be lost.")

    if not yes:
        click.confirm("Continue?", abort=True)

    typed = click.prompt(f"Type the database path exactly to confirm ({cfg.db_path})", default="", show_default=False)
    if typed.strip() != str(cfg.db_path):
        click.echo("Path mismatch — aborting.")
        raise click.Abort()

    # Remove any -wal / -shm files that SQLite may have left around.
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = cfg.db_path.with_name(cfg.db_path.name + suffix) if suffix else cfg.db_path
        if p.exists():
            p.unlink()
            click.echo(f"deleted {p}")
    click.echo("Done. Run `flea init` to recreate the schema.")


@cli.command("ping")
def ping_cmd() -> None:
    """Check connectivity to tarkov.dev."""
    cfg = load_config()
    with TarkovDevClient(cfg.tarkov_dev_api_url) as api:
        click.echo(f"tarkov.dev status: {api.ping()}")


@cli.command("fetch")
def fetch_cmd() -> None:
    """Fetch all items from tarkov.dev and record a price snapshot."""
    cfg = load_config()
    items, snaps = fetch_and_store(cfg)
    click.echo(f"items upserted: {items}, snapshots written: {snaps}")


@cli.command("fee")
@click.option("--base", "base_price", type=int, required=True, help="Item base price (VO).")
@click.option("--list", "list_price", type=int, required=True, help="Listing price (VR).")
@click.option("-q", "--quantity", type=int, default=1, show_default=True)
@click.option("--intel", "intel_center_level", type=int, default=None,
              help="Override Intelligence Center level (0-3).")
@click.option("--hideout-skill", "hideout_management_skill", type=int, default=None,
              help="Override Hideout Management skill (0-50).")
def fee_cmd(
    base_price: int,
    list_price: int,
    quantity: int,
    intel_center_level: int | None,
    hideout_management_skill: int | None,
) -> None:
    """Compute flea listing fee and net proceeds for a hypothetical listing."""
    cfg = load_config()
    intel = intel_center_level if intel_center_level is not None else cfg.intel_center_level
    skill = hideout_management_skill if hideout_management_skill is not None else cfg.hideout_management_skill
    fee = flea_listing_fee(
        base_price, list_price, quantity,
        intel_center_level=intel, hideout_management_skill=skill,
    )
    net = flea_net_proceeds(
        base_price, list_price, quantity,
        intel_center_level=intel, hideout_management_skill=skill,
    )
    click.echo(f"Base price:    {base_price:>14,}")
    click.echo(f"List price:    {list_price:>14,}")
    click.echo(f"Quantity:      {quantity:>14}")
    click.echo(f"Intel / Skill: {intel:>10} / {skill}")
    click.echo(f"Fee:           {fee:>14,}")
    click.echo(f"Net proceeds:  {net:>14,}")


@cli.command("llm-test")
def llm_test_cmd() -> None:
    """Smoke-test the LLM wiring: extraction on the cheap model, reasoning on the bigger one."""
    cfg = load_config()
    llm = make_llm_client(cfg)

    fake_patch_note = (
        "Patch 0.16.5 hotfix notes:\n"
        "- M61 7.62x51mm round damage reduced from 75 to 65.\n"
        "- LEDX Skin Transilluminator spawn rate increased by 30% on Labs and Shoreline.\n"
        "- Therapist purchase limit for Salewa reset bug fixed.\n"
        "Wipe planned for next Thursday."
    )

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["events"],
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["event_type", "affected_items", "direction", "confidence", "summary"],
                    "properties": {
                        "event_type": {
                            "type": "string",
                            "enum": ["nerf", "buff", "wipe", "event", "spawn_change", "other"],
                        },
                        "affected_items": {"type": "array", "items": {"type": "string"}},
                        "direction": {"type": "string", "enum": ["up", "down", "unclear"]},
                        "confidence": {"type": "number"},
                        "summary": {"type": "string"},
                    },
                },
            }
        },
    }

    click.echo(f"--- extract_structured (model: {llm.default_extraction_model}) ---")
    extracted = llm.extract_structured(
        system="You extract structured event data from Escape from Tarkov patch notes. "
        "Return one event per discrete change. 'direction' is the expected effect on "
        "the affected items' flea-market price.",
        user=fake_patch_note,
        schema=schema,
    )
    click.echo(json.dumps(extracted, indent=2))

    click.echo(f"\n--- reason (model: {llm.default_reasoning_model}) ---")
    answer = llm.reason(
        system="You are a Tarkov flea-market advisor. Be terse — two sentences max.",
        user=f"Given these events:\n{json.dumps(extracted)}\n\nShould I buy LEDX now or wait?",
    )
    click.echo(answer)


def _print_signals(title: str, signals: list[Signal]) -> None:
    click.echo(f"\n=== {title} ({len(signals)}) ===")
    if not signals:
        click.echo("  (none)")
        return
    for s in signals:
        name = (s.short_name or s.item_name)[:28]
        click.echo(f"  [{s.action:5}] {name:28}  score={s.score:>12,.0f}  {s.reasoning}")


@cli.command("scan")
@click.option(
    "--type", "signal_type",
    type=click.Choice(["all", "vendor_flip", "dip_buy", "crash"]),
    default="all", show_default=True,
)
@click.option("--limit", type=int, default=10, show_default=True)
def scan_cmd(signal_type: str, limit: int) -> None:
    """Rank current flea opportunities from the most recent snapshot."""
    cfg = load_config()
    with connect(cfg.db_path) as conn:
        if signal_type in ("all", "vendor_flip"):
            _print_signals("Vendor flips", vendor_flip_signals(conn, limit=limit))
        if signal_type in ("all", "dip_buy"):
            _print_signals("Dip buys", dip_buy_signals(conn, cfg, limit=limit))
        if signal_type in ("all", "crash"):
            _print_signals("48h crashes", crash_signals(conn, limit=limit))


@cli.command("advise")
@click.argument("item")
def advise_cmd(item: str) -> None:
    """Give a buy/hold/sell recommendation for ITEM. (not implemented yet)"""
    click.echo(f"advise {item}: not implemented yet")


@cli.command("watch")
def watch_cmd() -> None:
    """Run the polling daemon: price loop + news loop on configured intervals."""
    from flea.daemon import run

    cfg = load_config()
    run(cfg)


@cli.command("serve")
@click.option("--host", default=None, help="Override config server.host.")
@click.option("--port", type=int, default=None, help="Override config server.port.")
def serve_cmd(host: str | None, port: int | None) -> None:
    """Run the read-only HTTP API for the web UI / external clients."""
    from flea.server import run as run_server

    cfg = load_config()
    if host is not None:
        cfg.server_host = host
    if port is not None:
        cfg.server_port = port
    run_server(cfg)


@cli.group("news")
def news_grp() -> None:
    """News ingestion and event extraction."""


def _build_sources(cfg) -> list:
    sources = []
    enabled = cfg.news_sources or {}
    if enabled.get("reddit", True):
        sources.append(RedditSource())
    return sources


@news_grp.command("fetch")
@click.option("--limit", type=int, default=None,
              help="Override per-source post limit.")
@click.option("--dry-run", is_flag=True,
              help="Fetch and extract, but don't write to the database.")
def news_fetch_cmd(limit: int | None, dry_run: bool) -> None:
    """Pull fresh articles, extract events, and store them."""
    cfg = load_config()
    init_db(cfg.db_path)
    llm = make_llm_client(cfg)
    extractor = Extractor(llm)
    sources = _build_sources(cfg)
    if not sources:
        click.echo("No news sources enabled.")
        return

    now = int(time.time())
    new_articles = 0
    skipped = 0
    total_events = 0

    with connect(cfg.db_path) as conn:
        for src in sources:
            if limit is not None and hasattr(src, "limit"):
                src.limit = limit
            click.echo(f"Fetching from {src.name}...")
            try:
                articles = src.fetch()
            except Exception as e:
                click.echo(f"  error: {e}")
                continue
            click.echo(f"  {len(articles)} candidate articles")

            for art in articles:
                if article_exists(conn, art.url):
                    skipped += 1
                    continue

                try:
                    events = extractor.extract(art)
                except Exception as e:
                    click.echo(f"  extraction failed for {art.url}: {e}")
                    continue

                if dry_run:
                    if events:
                        click.echo(f"  [dry] {art.title[:60]}: {len(events)} event(s)")
                    new_articles += 1
                    total_events += len(events)
                    continue

                store_article(conn, art, fetched_at=now)
                new_articles += 1
                for ev in events:
                    store_event(conn, art.url, ev, created_at=now)
                    total_events += 1
                if events:
                    click.echo(f"  + {art.title[:60]}: {len(events)} event(s)")
            if not dry_run:
                conn.commit()

    click.echo(
        f"Done. new articles: {new_articles}, "
        f"already-seen: {skipped}, events: {total_events}"
        + (" (dry-run, nothing persisted)" if dry_run else "")
    )


@news_grp.command("list")
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--min-confidence", type=float, default=0.0, show_default=True)
def news_list_cmd(limit: int, min_confidence: float) -> None:
    """Show recent extracted events."""
    cfg = load_config()
    with connect(cfg.db_path) as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.event_type, e.direction, e.confidence,
                   e.time_horizon, e.summary, e.created_at,
                   a.title AS article_title, a.source AS article_source
            FROM events e
            LEFT JOIN news_articles a ON a.url = e.article_url
            WHERE e.confidence >= ?
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT ?
            """,
            (min_confidence, limit),
        ).fetchall()

        if not rows:
            click.echo("(no events)")
            return

        for row in rows:
            items = conn.execute(
                """
                SELECT i.short_name, i.name
                FROM event_items ei
                JOIN items i ON i.id = ei.item_id
                WHERE ei.event_id = ?
                """,
                (row["id"],),
            ).fetchall()
            item_str = ", ".join(it["short_name"] or it["name"] for it in items) or "-"
            click.echo(
                f"[{row['event_type']:12}] dir={row['direction']:7} "
                f"conf={row['confidence']:.2f} horizon={row['time_horizon']:9} "
                f"items={item_str}"
            )
            click.echo(f"    {row['summary']}")
            if row["article_title"]:
                click.echo(
                    f"    src={row['article_source']} | {row['article_title'][:80]}"
                )


if __name__ == "__main__":
    cli()
