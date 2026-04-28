import asyncio

from portfolio import estimate_portfolio_value, get_cash, get_open_positions
from alerts import send_alert

STARTING_VALUE = 1000.0


async def portfolio_summary_message(price_lookup):
    value = await estimate_portfolio_value(price_lookup)
    cash = await get_cash()
    positions = await get_open_positions()

    pnl = value - STARTING_VALUE
    pnl_pct = pnl / STARTING_VALUE * 100

    return (
        f"📊 Portfolio Summary\n"
        f"Portfolio value: ${value:,.2f}\n"
        f"P/L: ${pnl:,.2f} ({pnl_pct:.2f}%)\n"
        f"Cash: ${cash:,.2f}\n"
        f"Active positions: {len(positions)}"
    )


async def send_portfolio_summary(price_lookup):
    msg = await portfolio_summary_message(price_lookup)
    await send_alert(msg)


async def hourly_summary(price_lookup):
    while True:
        await send_portfolio_summary(price_lookup)
        await asyncio.sleep(3600)
