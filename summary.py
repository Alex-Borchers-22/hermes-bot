import asyncio

from portfolio import estimate_portfolio_value, get_cash, get_open_positions
from alerts import send_alert


async def hourly_summary(price_lookup):
    while True:
        value = await estimate_portfolio_value(price_lookup)
        cash = await get_cash()
        positions = await get_open_positions()

        starting_value = 1000.0
        pnl = value - starting_value
        pnl_pct = pnl / starting_value * 100

        msg = (
            f"📊 Hourly Portfolio Summary\n"
            f"Portfolio value: ${value:,.2f}\n"
            f"P/L: ${pnl:,.2f} ({pnl_pct:.2f}%)\n"
            f"Cash: ${cash:,.2f}\n"
            f"Active positions: {len(positions)}"
        )

        await send_alert(msg)

        await asyncio.sleep(3600)
