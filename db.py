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

        await db.commit()