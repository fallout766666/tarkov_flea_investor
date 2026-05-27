# tarkov-flea-investor

Decision-support agent for the Escape from Tarkov flea market. Pulls live
prices from [tarkov.dev](https://tarkov.dev), ingests game news from Reddit
(and later BSG sources), and surfaces buy/sell/watch signals through a CLI
and a small web dashboard.

This tool **does not interact with the game**. It does not read game memory,
inject input, or automate any action — it only gives you information so you
can act in-game yourself. Compliant with EFT EULA and BattlEye.

## Features

- 5044+ items snapshotted from tarkov.dev on a schedule, building a local
  price history (the API itself doesn't expose history — we record it).
- Rule-based signals: **vendor flips** (flea → trader, no fees), **dip buys**
  (with proper flea-fee math), **48h crashes** (down ≥25%).
- News ingestion from r/EscapefromTarkov with LLM event extraction
  (nerfs, buffs, wipes, spawn changes, in-game events).
- Tiered LLM strategy: cheap nano model for extraction, bigger model for
  reasoning.
- Two independent processes: a **daemon** that polls and writes, and a
  read-only **HTTP server** with a single-page dashboard for the same data.
- Single SQLite database. CLI tools, daemon, and server all share it
  safely (one writer, many readers).

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

1. **Secrets.** Copy `.env.example` to `.env` and fill in:
   - `OPENAI_API_KEY` — required for news extraction and reasoning.
   - `FLEA_API_KEY` — required to run the web server. Generate a strong
     value, e.g.
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

2. **Config file.** Copy `config.example.toml` to `config.toml` and adjust:
   - `[flea] intel_center_level` / `hideout_management_skill` — your in-game
     state. Affects the fee calculator and `dip_buy` net-proceeds math.
   - `[poll]` intervals — defaults: 300s price, 1800s news.
   - `[llm]` models — change extraction/fusion models if needed.
   - `[server] host` / `port` / `allowed_ips` — bind address for the web
     server. Keep `127.0.0.1` for local dev; use a specific LAN IP on a
     deployment machine (avoid `0.0.0.0`). Populate `allowed_ips` to
     restrict which clients can hit the API even with the key.

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
| `db reset [--yes]` | Delete the database. Requires y/N confirm **and** typing the exact DB path. |

### Long-running processes

These two are designed to run side-by-side in their own terminals (or as
auto-started services on a deployment machine).

```bash
python -m flea watch    # data collector (writes)
python -m flea serve    # web API + dashboard (reads)
```

**`flea watch`** — the daemon. Runs two loops in parallel:

- **Price loop** (every `price_interval_seconds`): fetches the catalog,
  writes a snapshot row per item, runs all three rule signals, and persists
  them to the `signals` table.
- **News loop** (every `news_interval_seconds`): pulls Reddit, extracts
  events via the nano model on new articles only (deduped by URL so re-runs
  cost nothing), persists articles and events.

Logs go to `logs/flea.log` (rotated at 2 MB × 3 files) and to stdout. Stop
with `Ctrl-C` (graceful — current cycles finish first).

**`flea serve`** — the HTTP server. Read-only access to the database.

- Dashboard at `http://<host>:<port>/` — three tabs: signals, events, item
  price history with charts. Paste your `FLEA_API_KEY` once, it persists in
  the browser.
- JSON endpoints (all require `X-API-Key` header except `/health`):
  - `GET /health` — daemon liveness via last-snapshot timestamps.
  - `GET /signals?type=&limit=` — latest signal emit, filterable by type.
  - `GET /events?min_confidence=&limit=` — recent events.
  - `GET /items?q=&limit=` — name/short-name search.
  - `GET /items/{id}/history?window=24h|7d|30d` — price snapshots over a window.
- Refuses to start if `FLEA_API_KEY` is unset, to prevent accidental
  open access.
- `--host` / `--port` flags override config for ad-hoc runs (e.g. exposing
  a local instance to your LAN without editing `config.toml`).

The daemon and the server are deliberately separate processes — you can
restart the web layer for code/config changes without interrupting an
in-flight news fetch.

## Architecture

```
┌─ flea watch (daemon) ────────┐    ┌─ flea serve (HTTP) ──────────┐
│  price thread → fetch + sigs │    │  uvicorn + FastAPI           │
│  news thread  → reddit + LLM │    │  /  (static dashboard)       │
└──────────────┬───────────────┘    │  /signals /events /items ... │
               │                    └──────────────┬───────────────┘
               │                                   │
               └──────── SQLite (data/flea.db) ────┘
                              ▲
                              │
            CLI processes (scan, news list, fee, ...)
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

Wipe everything with `flea db reset` (double-confirmation required) and run
`flea init` again.

## A note on prices

`last_low_price` (minimum active listing) is the canonical price the agent
reasons about. The 24h average is shown as secondary context but should
**not** be trusted — it's polluted by intentionally-inflated listings used
for real-money-trade gifting and friend transfers (EFT has no direct trade,
so players post absurd listings the recipient buys). Last-low is what items
actually clear at.

## License

MIT. See [LICENSE](LICENSE).
