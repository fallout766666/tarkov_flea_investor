from dataclasses import dataclass
from sqlite3 import Connection

from flea.config import Config
from flea.fees import flea_net_proceeds

MIN_PRICE = 1000
MIN_PROFIT = 1000


@dataclass
class Signal:
    item_id: str
    item_name: str
    short_name: str | None
    signal_type: str
    action: str
    score: float
    reasoning: str


_LATEST_PER_ITEM = """
SELECT
    s.item_id,
    s.captured_at,
    s.last_low_price,
    s.avg_24h_price,
    s.change_last_48h_pct,
    s.best_trader_name,
    s.best_trader_price,
    i.name,
    i.short_name,
    i.base_price
FROM price_snapshots s
JOIN items i ON i.id = s.item_id
WHERE s.captured_at = (
    SELECT MAX(captured_at) FROM price_snapshots WHERE item_id = s.item_id
)
"""


def vendor_flip_signals(conn: Connection, limit: int = 20) -> list[Signal]:
    """Items where buying on flea and selling to a trader is profitable.

    No fees on this path (selling to trader doesn't trigger flea fees).
    """
    rows = conn.execute(
        f"""
        WITH latest AS ({_LATEST_PER_ITEM})
        SELECT * FROM latest
        WHERE last_low_price IS NOT NULL
          AND best_trader_price IS NOT NULL
          AND last_low_price >= ?
          AND best_trader_price - last_low_price >= ?
        ORDER BY (best_trader_price - last_low_price) DESC
        LIMIT ?
        """,
        (MIN_PRICE, MIN_PROFIT, limit),
    ).fetchall()

    out: list[Signal] = []
    for r in rows:
        profit = r["best_trader_price"] - r["last_low_price"]
        roi = profit * 100.0 / r["last_low_price"]
        out.append(
            Signal(
                item_id=r["item_id"],
                item_name=r["name"],
                short_name=r["short_name"],
                signal_type="vendor_flip",
                action="buy",
                score=profit,
                reasoning=(
                    f"Buy flea {r['last_low_price']:,}R "
                    f"-> sell {r['best_trader_name']} {r['best_trader_price']:,}R "
                    f"= +{profit:,}R ({roi:.1f}% ROI)"
                ),
            )
        )
    return out


def dip_buy_signals(conn: Connection, cfg: Config, limit: int = 20) -> list[Signal]:
    """Items trading well below their 24h average where reselling on flea at
    the average price yields a profitable net (after listing fee)."""
    dip_ratio = 1.0 - cfg.dip_threshold_pct / 100.0
    rows = conn.execute(
        f"""
        WITH latest AS ({_LATEST_PER_ITEM})
        SELECT * FROM latest
        WHERE last_low_price IS NOT NULL
          AND avg_24h_price IS NOT NULL
          AND last_low_price >= ?
          AND avg_24h_price > 0
          AND last_low_price < avg_24h_price * ?
        """,
        (MIN_PRICE, dip_ratio),
    ).fetchall()

    out: list[Signal] = []
    for r in rows:
        if not r["base_price"]:
            continue
        net = flea_net_proceeds(
            r["base_price"],
            r["avg_24h_price"],
            intel_center_level=cfg.intel_center_level,
            hideout_management_skill=cfg.hideout_management_skill,
        )
        profit = net - r["last_low_price"]
        if profit < MIN_PROFIT:
            continue
        dip_pct = (r["last_low_price"] - r["avg_24h_price"]) * 100.0 / r["avg_24h_price"]
        roi = profit * 100.0 / r["last_low_price"]
        out.append(
            Signal(
                item_id=r["item_id"],
                item_name=r["name"],
                short_name=r["short_name"],
                signal_type="dip_buy",
                action="buy",
                score=profit,
                reasoning=(
                    f"Buy {r['last_low_price']:,}R ({dip_pct:+.1f}% vs 24h avg {r['avg_24h_price']:,}R), "
                    f"relist at avg net {net:,}R = +{profit:,}R ({roi:.1f}% ROI)"
                ),
            )
        )

    out.sort(key=lambda s: s.score, reverse=True)
    return out[:limit]


def store_signals(conn: Connection, signals: list[Signal], created_at: int) -> int:
    for s in signals:
        conn.execute(
            """
            INSERT INTO signals (item_id, signal_type, action, score, reasoning, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (s.item_id, s.signal_type, s.action, s.score, s.reasoning, created_at),
        )
    return len(signals)


def crash_signals(conn: Connection, threshold_pct: float = -25.0, limit: int = 20) -> list[Signal]:
    """Items down sharply in 48h — possible nerf / dump / wipe pressure.
    Surfaced for investigation rather than auto-buy."""
    rows = conn.execute(
        f"""
        WITH latest AS ({_LATEST_PER_ITEM})
        SELECT * FROM latest
        WHERE last_low_price IS NOT NULL
          AND change_last_48h_pct IS NOT NULL
          AND last_low_price >= ?
          AND change_last_48h_pct <= ?
        ORDER BY change_last_48h_pct ASC
        LIMIT ?
        """,
        (MIN_PRICE, threshold_pct, limit),
    ).fetchall()

    out: list[Signal] = []
    for r in rows:
        out.append(
            Signal(
                item_id=r["item_id"],
                item_name=r["name"],
                short_name=r["short_name"],
                signal_type="crash",
                action="watch",
                score=-r["change_last_48h_pct"],
                reasoning=(
                    f"Down {r['change_last_48h_pct']:.1f}% in 48h at {r['last_low_price']:,}R - "
                    f"investigate before buying"
                ),
            )
        )
    return out
