# tarkov-flea-investor

Decision-support agent for the Escape from Tarkov flea market. Pulls live
prices from [tarkov.dev](https://tarkov.dev), ingests game news from Reddit
(and later BSG sources), and surfaces buy/sell/watch signals.

This tool **does not interact with the game**. It does not read game memory,
inject input, or automate any action — it only gives you information so you
can act in-game yourself. Compliant with EFT EULA and BattlEye.

## Features

- 5044+ items snapshotted from tarkov.dev every 5 min, building a local price history.
- Rule-based signals: **vendor flips** (flea → trader, no fees), **dip buys**
  (with proper flea-fee math), **48h crashes** (down ≥25%).
- News ingestion from r/EscapefromTarkov with LLM event extraction
  (nerfs, buffs, wipes, spawn changes, in-game events).
- Tiered LLM strategy: cheap nano model for extraction, bigger model for
  reasoning. Defaults eligible for OpenAI's free daily token pool when
  prompt sharing is on.
- Single SQLite database; CLI commands and the background daemon read/write
  the same file safely.

## Setup

Requires Python 3.13+.

```bash
git clone https://github.com/fallout766666/tarkov-flea-investor.git
cd tarkov-flea-investor
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

### Configuration

1. **API key.** Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY`.

   To use OpenAI's free daily tokens, enable prompt sharing at
   <https://platform.openai.com/settings/organization/data-controls>.
   Eligible models include `gpt-5.4-nano` (2.5M tokens/day) and
   `gpt-5.4` (250k tokens/day).

2. **Config file.** Copy `config.example.toml` to `config.toml` and adjust:
   - `[flea] intel_center_level` / `hideout_management_skill` — your in-game
     state. Affects the fee calculator and `dip_buy` net-proceeds math.
   - `[poll]` intervals — defaults: 300s price, 1800s news.
   - `[llm]` models — change extraction/fusion models if needed.

3. **Initialize the DB.**

   ```bash
   python -m flea init
   ```

## Usage

All commands are invoked via `python -m flea <command>`.

### One-off commands

| Command | Description |
| --- | --- |
| `init` | Create the SQLite database with the current schema. |
| `ping` | Verify connectivity to tarkov.dev. |
| `fetch` | Pull all items + write one price snapshot. |
| `scan [--type {all,vendor_flip,dip_buy,crash}] [--limit N]` | Rank current opportunities from the latest snapshot. |
| `fee --base VO --list VR [-q N] [--intel L] [--hideout-skill S]` | Compute flea listing fee + net proceeds for a hypothetical listing. |
| `news fetch [--limit N] [--dry-run]` | Pull articles, extract events via LLM, persist. |
| `news list [--limit N] [--min-confidence X]` | Show recent extracted events. |
| `llm-test` | Smoke-test both LLM models on a fake patch note. |

### Background daemon

```bash
python -m flea watch
```

Runs two loops in parallel:

- **Price loop** (every `price_interval_seconds`): fetches the catalog,
  writes a snapshot row per item, runs all three rule signals, and persists
  them to the `signals` table.
- **News loop** (every `news_interval_seconds`): pulls Reddit, extracts
  events via the nano model, persists articles and events.

Logs go to `logs/flea.log` (rotated at 2 MB × 3 files) and to stdout. Stop
the daemon with `Ctrl-C` (graceful shutdown — current cycles finish, then
threads exit).

CLI commands can be run from a separate terminal while the daemon is
running. SQLite handles concurrent readers and the single writer.

## Architecture

```
┌─ daemon process ──────────────────┐
│  price thread → fetch + signals   │
│  news thread  → reddit + LLM      │
│  (web thread, future)             │
└──────────────┬────────────────────┘
               │  SQLite (data/flea.db)
               │
       CLI processes (separate, on-demand)
       └─ scan / news list / fee / advise
```

Tiers of analysis:

1. **Fetch** — deterministic API pulls, snapshots written.
2. **Rule signals** — pure SQL over latest snapshot.
3. **News extraction** — nano model converts free-text posts to typed events.
4. **Fusion** *(future)* — bigger model combines signals + news for
   triggered, item-specific recommendations.
5. **Alerts** *(future)* — push notifications when fusion crosses a threshold.

## Database

Tables in `data/flea.db`:

- `items` — item catalog (id, name, short_name, base_price).
- `price_snapshots` — append-only price history per item.
- `news_articles` — deduped by URL.
- `events`, `event_items` — structured events extracted from articles.
- `signals` — append-only feed of every signal the daemon emits.

## License

MIT. See [LICENSE](LICENSE).
