import time

from flea.api import TarkovDevClient
from flea.config import Config
from flea.storage import connect, init_db


def best_trader_offer(sell_for: list[dict] | None) -> tuple[str | None, int | None]:
    best_name: str | None = None
    best_price = -1
    for offer in sell_for or []:
        vendor = (offer.get("vendor") or {}).get("name")
        price = offer.get("priceRUB")
        if vendor is None or vendor == "Flea Market" or price is None:
            continue
        if price > best_price:
            best_price = price
            best_name = vendor
    return best_name, (best_price if best_price >= 0 else None)


def fetch_and_store(cfg: Config) -> tuple[int, int]:
    """Fetch all items from tarkov.dev and persist them with a price snapshot.

    Returns (items_upserted, snapshots_written).
    """
    init_db(cfg.db_path)
    now = int(time.time())

    with TarkovDevClient(cfg.tarkov_dev_api_url) as api:
        items = api.fetch_items()

    items_upserted = 0
    snapshots_written = 0

    with connect(cfg.db_path) as conn:
        for item in items:
            conn.execute(
                """
                INSERT INTO items (id, name, short_name, base_price, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    short_name = excluded.short_name,
                    base_price = excluded.base_price,
                    updated_at = excluded.updated_at
                """,
                (
                    item["id"],
                    item["name"],
                    item.get("shortName"),
                    item.get("basePrice"),
                    now,
                ),
            )
            items_upserted += 1

            last_low = item.get("lastLowPrice")
            avg_24h = item.get("avg24hPrice")
            if last_low is None and avg_24h is None:
                continue

            trader_name, trader_price = best_trader_offer(item.get("sellFor"))
            conn.execute(
                """
                INSERT OR IGNORE INTO price_snapshots (
                    item_id, captured_at,
                    last_low_price, avg_24h_price, change_last_48h_pct,
                    best_trader_name, best_trader_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    now,
                    last_low,
                    avg_24h,
                    item.get("changeLast48hPercent"),
                    trader_name,
                    trader_price,
                ),
            )
            snapshots_written += 1

        conn.commit()

    return items_upserted, snapshots_written
