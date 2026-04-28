# Hermes bot — paper trading strategy (current)

## Goals (what we’re building toward)

1. **Mock a $1,000 portfolio** and keep a durable record of where we stand. The implementation uses **SQLite** (`paper_portfolio.db` via `db.py` / `aiosqlite`) with a single `portfolio` row, `positions` for open (and future closed) legs, and **`transactions` for a full log of every paper buy** (slug, action, side, price, shares, notional, portfolio value at the time, reason, timestamp).

2. **When “buy” context is strong, simulate buying the contract**, track value and P/L sensibly, and size positions at roughly **5–10% of portfolio** with **size that scales with performance** (bigger when ahead, smaller when behind — see `position_pct_from_performance` in `portfolio.py`).

3. **Poll the market on a 1-minute cadence** so signals refresh frequently without hammering the network unrealistically (see `TICK = 60` in `main.py`).

4. **All transactions are logged in SQLite** so you can review them daily (query `transactions` / export). Separately, **at each hour** the bot sends a **Telegram** summary: portfolio value, P/L vs. the $1k start, cash, and count of open positions (`summary.py`).

---

## How the running bot behaves (from the code)

**Universe:** On startup, the app loads the top markets by 24h volume from Polymarket’s Gamma API (`get_top_market_slugs`, default **10** markets) and runs one async **monitor** loop per slug in parallel, plus a background **hourly summary** task.

**Each tick (every 60s):** For each market, it pulls an order book snapshot (Gamma for metadata, CLOB for the book) and keeps a `latest_prices` map for **mark-to-market** in `estimate_portfolio_value`.

**Signals (no ML — rule-based):** Comparing consecutive snapshots, `diff()` gives **price change** and **order-book imbalance** (roughly bid vs. ask size pressure). The bot can alert on large price moves and imbalance. **Paper buy** is attempted only when both are strong: in code, `abs(d["imbalance"]) > 0.6` and `abs(d["price_delta"]) > 0.02`, then **YES vs. NO** follows imbalance sign. NO entries use an implied **complement** of the YES mid (since the snapshot is YES-centric) — revisit if you need the actual NO token mid from the CLOB.

**Position sizing:** Each paper buy size is `portfolio_value * position_pct_from_performance(...)`, capped by available **cash** and a **minimum $5** notional. One open position per slug at a time; duplicates are skipped with “Already holding”.

**Alerts:** Telegram is used for price/imbalance notices, each successful paper buy, and the hourly roll-up.

---

## Historical snapshots & backtesting (collect your own data)

This is the realistic path to validate rules before paying for third-party historical order books.

**What gets stored:** On each poll (same cadence as `TICK` in `main.py`), after `fetch_snapshot`, the bot inserts into SQLite table **`market_snapshots`** (`slug`, `ts` UTC ISO, `yes_price`, `bid_size`, `ask_size`, `spread`). Schema and insert live in **`db.py`** (`init_db` + `record_snapshot`).

**Replay:** After **7–30 days** of collection, run **`backtest.py`** against your DB. It loads snapshots for a slug in time order and replays the same logic as **`monitor`**: consecutive snapshots → `diff` → spread / imbalance / price-delta rules → streak confirms → paper-style buys; take-profit / stop-loss exits use the same multipliers as live (**`EXIT_TAKE_PROFIT_MULT` / `EXIT_STOP_LOSS_MULT`** in **`strategy.py`**). The simulator does **not** write to `paper_portfolio.db`; it only reads snapshots.

```bash
python backtest.py --slug YOUR_MARKET_SLUG
python backtest.py --slug YOUR_MARKET_SLUG --db paper_portfolio.db -v
```

**Suggested phases**

1. **Collect** snapshots for at least a week (longer is better for rare regimes).
2. **Backtest** offline with `backtest.py`; tune **`strategy.py`** thresholds.
3. **Iterate** parameters against stored data until metrics look acceptable.
4. **Paper trade live** again with revised settings and compare to replay expectations.

Entry/exit and screening knobs live in **`strategy.py`** so one file drives live trading and offline replay.

---

## Future plans

- **Daily review:** Intentionally make time to scan `transactions` and the hourly Telegram history; optionally add a small **CLI or report script** that groups fills by day and by slug.
- **Evolving the strategy:** Tune thresholds in **`strategy.py`**, use **per-market** or **volatility-adjusted** rules, and refine **NO-side pricing** using the actual NO token book when needed.
- **Real capital:** After paper results are trusted, size live trades with strict limits and a separate risk review (keys, account safeguards, and legal/compliance in your jurisdiction).
- **Execution automation via Polymarket:** Replace `paper_buy` with **CLOB or official API** order placement (limits, idempotency, error handling, retries), with **separate** paper vs. live config and a clear “kill switch.”

This architecture (SQLite ledger + mark-to-market + rules + external alerts) is a deliberate **staging ground** before touching real trading infrastructure.

---

## Ubuntu: restart the bot and dashboard

Paths and unit names depend on how you deployed (adjust to match your setup). Typical pattern: **two** processes — **`main.py`** (bot) and **`uvicorn`** for **`dashboard.py`**.

**systemd (replace unit names with yours, e.g. from `/etc/systemd/system/`):**

```bash
sudo systemctl restart hermes-bot
sudo systemctl status hermes-bot

sudo systemctl restart hermes-dashboard
sudo systemctl status hermes-dashboard
```

View logs:

```bash
sudo journalctl -u hermes-bot -f
sudo journalctl -u hermes-dashboard -f
```

After editing a unit file: `sudo systemctl daemon-reload` then restart the service.

If you are **not** using systemd, restart whatever supervises the same commands (Docker, Supervisor, `screen`/`tmux`, etc.).

---

## Dashboard URL (Droplet)

The FastAPI app is **`dashboard.py`**. When bound to all interfaces (as in the module docstring), open a browser to:

`http://[drop-ip]:8000`

Replace **`[drop-ip]`** with your Droplet’s (or any VPS) public IPv4 address—for example `http://203.0.113.45:8000`.

- Allow **TCP port 8000** in the cloud provider’s firewall and/or **`ufw`** on the VM (`sudo ufw allow 8000/tcp` then `sudo ufw reload`) if traffic is blocked.
- Binding `0.0.0.0` exposes the UI to the network; restrict by firewall/VPN if the host is on the public internet.

**Local-only alternative (SSH tunnel from your machine):**

```bash
ssh -L 8000:localhost:8000 user@YOUR_DROPLET_PUBLIC_IP
```

Then open **http://localhost:8000** on your laptop.
