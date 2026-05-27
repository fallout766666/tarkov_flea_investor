import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    db_path: Path
    log_path: Path
    price_interval_seconds: int
    news_interval_seconds: int
    intel_center_level: int
    hideout_management_skill: int
    watchlist: list[str]
    dip_threshold_pct: float
    sell_threshold_pct: float
    trend_window_days: int
    llm_provider: str
    extraction_model: str
    fusion_model: str
    news_sources: dict[str, bool] = field(default_factory=dict)

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    tarkov_dev_api_url: str = "https://api.tarkov.dev/graphql"


def load_config(config_path: Path | None = None) -> Config:
    load_dotenv()

    if config_path is None:
        config_path = Path("config.toml")
        if not config_path.exists():
            config_path = Path("config.example.toml")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    return Config(
        db_path=Path(raw["paths"]["db"]),
        log_path=Path(raw["paths"]["log"]),
        price_interval_seconds=raw["poll"]["price_interval_seconds"],
        news_interval_seconds=raw["poll"]["news_interval_seconds"],
        intel_center_level=raw["flea"]["intel_center_level"],
        hideout_management_skill=raw["flea"]["hideout_management_skill"],
        watchlist=raw["watchlist"]["items"],
        dip_threshold_pct=raw["signals"]["dip_threshold_pct"],
        sell_threshold_pct=raw["signals"]["sell_threshold_pct"],
        trend_window_days=raw["signals"]["trend_window_days"],
        llm_provider=raw["llm"]["provider"],
        extraction_model=raw["llm"]["extraction_model"],
        fusion_model=raw["llm"]["fusion_model"],
        news_sources=raw.get("news", {}).get("sources", {}),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        tarkov_dev_api_url=os.getenv(
            "TARKOV_DEV_API_URL", "https://api.tarkov.dev/graphql"
        ),
    )
