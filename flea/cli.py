import json

import click

from flea import __version__
from flea.api import TarkovDevClient
from flea.config import load_config
from flea.fees import flea_listing_fee, flea_net_proceeds
from flea.fetcher import fetch_and_store
from flea.llm import make_llm_client
from flea.storage import init_db


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


@cli.command("scan")
def scan_cmd() -> None:
    """Rank current flea opportunities. (not implemented yet)"""
    click.echo("scan: not implemented yet")


@cli.command("advise")
@click.argument("item")
def advise_cmd(item: str) -> None:
    """Give a buy/hold/sell recommendation for ITEM. (not implemented yet)"""
    click.echo(f"advise {item}: not implemented yet")


@cli.command("watch")
def watch_cmd() -> None:
    """Run the polling daemon. (not implemented yet)"""
    click.echo("watch: not implemented yet")


if __name__ == "__main__":
    cli()
