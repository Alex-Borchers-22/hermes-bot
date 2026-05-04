import aiosqlite
from datetime import datetime, timezone

DB_PATH = "paper_portfolio.db"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL NOT NULL,
            starting_value REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            shares REAL NOT NULL,
            cost REAL NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            exit_price REAL,
            realized_pnl REAL
        )
        """)

        cols = {row[1] for row in await db.execute_fetchall("PRAGMA table_info(positions)")}
        if "topic" not in cols:
            await db.execute("ALTER TABLE positions ADD COLUMN topic TEXT")
        if "condition_id" not in cols:
            await db.execute("ALTER TABLE positions ADD COLUMN condition_id TEXT")
        if "settlement_tx_hash" not in cols:
            await db.execute("ALTER TABLE positions ADD COLUMN settlement_tx_hash TEXT")
        if "settlement_log_index" not in cols:
            await db.execute("ALTER TABLE positions ADD COLUMN settlement_log_index INTEGER")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            action TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            shares REAL NOT NULL,
            notional REAL NOT NULL,
            portfolio_value REAL NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """)

        row = await db.execute_fetchall("SELECT id FROM portfolio WHERE id = 1")
        if not row:
            await db.execute(
                "INSERT INTO portfolio (id, cash, starting_value, updated_at) VALUES (1, ?, ?, ?)",
                (1000.0, 1000.0, now_iso())
            )

        await db.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            ts TEXT NOT NULL,
            yes_price REAL NOT NULL,
            bid_size REAL NOT NULL,
            ask_size REAL NOT NULL,
            spread REAL NOT NULL
        )
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_snapshots_slug_ts
        ON market_snapshots(slug, ts)
        """)

        await db.commit()


async def record_snapshot(snapshot):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO market_snapshots (
                slug, ts, yes_price, bid_size, ask_size, spread
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            snapshot.slug,
            now_iso(),
            snapshot.yes_price,
            snapshot.bid_size,
            snapshot.ask_size,
            snapshot.spread,
        ))
        await db.commit()