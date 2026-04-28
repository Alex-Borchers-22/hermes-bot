import aiosqlite
from db import DB_PATH, now_iso


MIN_POSITION_PCT = 0.05
MAX_POSITION_PCT = 0.10


async def get_cash():
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("SELECT cash FROM portfolio WHERE id = 1")
        return float(rows[0][0])


async def get_open_positions():
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("""
            SELECT id, slug, side, entry_price, shares, cost, opened_at
            FROM positions
            WHERE closed_at IS NULL
        """)
        return rows


async def estimate_portfolio_value(price_lookup):
    cash = await get_cash()
    positions = await get_open_positions()

    unrealized = 0.0

    for pos in positions:
        _, slug, side, entry_price, shares, cost, _ = pos
        current_price = await price_lookup(slug)

        if current_price is None:
            current_price = entry_price

        unrealized += shares * current_price

    return cash + unrealized


def position_pct_from_performance(portfolio_value: float, starting_value: float = 1000.0):
    performance = (portfolio_value - starting_value) / starting_value

    if performance > 0.10:
        return 0.10
    if performance < -0.10:
        return 0.05

    return 0.075


async def already_holding(slug):
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("""
            SELECT id FROM positions
            WHERE slug = ? AND closed_at IS NULL
        """, (slug,))
        return bool(rows)


async def get_open_position_by_slug(slug):
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall("""
            SELECT id, slug, side, entry_price, shares, cost, opened_at
            FROM positions
            WHERE slug = ? AND closed_at IS NULL
        """, (slug,))
        return rows[0] if rows else None


async def paper_buy(slug, side, price, portfolio_value, reason):
    if await already_holding(slug):
        return False, "Already holding"

    cash = await get_cash()
    pct = position_pct_from_performance(portfolio_value)
    notional = portfolio_value * pct

    notional = min(notional, cash)

    if notional < 5:
        return False, "Not enough cash"

    shares = notional / price

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO positions (
                slug, side, entry_price, shares, cost, opened_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (slug, side, price, shares, notional, now_iso()))

        await db.execute("""
            INSERT INTO transactions (
                slug, action, side, price, shares, notional,
                portfolio_value, reason, created_at
            )
            VALUES (?, 'BUY', ?, ?, ?, ?, ?, ?, ?)
        """, (slug, side, price, shares, notional, portfolio_value, reason, now_iso()))

        await db.execute("""
            UPDATE portfolio
            SET cash = cash - ?, updated_at = ?
            WHERE id = 1
        """, (notional, now_iso()))

        await db.commit()

    return True, f"Bought ${notional:.2f} of {slug} at {price:.3f}"


async def paper_sell(slug, exit_price, portfolio_value, reason):
    pos = await get_open_position_by_slug(slug)
    if not pos:
        return False, "No open position"

    pos_id, _slug, side, _entry_price, shares, cost, _opened = pos
    proceeds = shares * exit_price
    realized_pnl = proceeds - cost

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE positions
            SET closed_at = ?, exit_price = ?, realized_pnl = ?
            WHERE id = ?
        """, (now_iso(), exit_price, realized_pnl, pos_id))

        await db.execute("""
            INSERT INTO transactions (
                slug, action, side, price, shares, notional,
                portfolio_value, reason, created_at
            )
            VALUES (?, 'SELL', ?, ?, ?, ?, ?, ?, ?)
        """, (
            slug,
            side,
            exit_price,
            shares,
            proceeds,
            portfolio_value,
            reason,
            now_iso(),
        ))

        await db.execute("""
            UPDATE portfolio
            SET cash = cash + ?, updated_at = ?
            WHERE id = 1
        """, (proceeds, now_iso()))

        await db.commit()

    return (
        True,
        f"Sold ${proceeds:.2f} of {slug} ({side}) at {exit_price:.3f} "
        f"(realized P/L ${realized_pnl:+,.2f})",
    )