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

## Future plans

- **Daily review:** Intentionally make time to scan `transactions` and the hourly Telegram history; optionally add a small **CLI or report script** that groups fills by day and by slug.
- **Evolving the strategy:** Tune thresholds (e.g. `0.6` / `0.02` / `0.05` alerts), add **exits** (take-profit / stop / time-based), use **per-market** or **volatility-adjusted** rules, and refine **NO-side pricing** using the actual NO token book when needed.
- **Real capital:** After paper results are trusted, size live trades with strict limits and a separate risk review (keys, account safeguards, and legal/compliance in your jurisdiction).
- **Execution automation via Polymarket:** Replace `paper_buy` with **CLOB or official API** order placement (limits, idempotency, error handling, retries), with **separate** paper vs. live config and a clear “kill switch.”

This architecture (SQLite ledger + mark-to-market + rules + external alerts) is a deliberate **staging ground** before touching real trading infrastructure.
