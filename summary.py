import asyncio

from portfolio import estimate_portfolio_value, get_cash, get_open_positions
from alerts import send_alert

STARTING_VALUE = 1000.0


def _trim_slug(slug: str, max_len: int = 52) -> str:
    if len(slug) <= max_len:
        return slug
    return slug[: max_len - 3] + "..."


async def _format_positions_block(price_lookup, positions) -> str:
    if not positions:
        return "Positions:\n(none)"

    lines: list[str] = [f"Positions ({len(positions)}):"]
    for pos in positions:
        _, slug, side, entry_price, shares, cost, _, _topic = pos[:8]
        yes_mid = await price_lookup(slug)
        if yes_mid is None:
            leg = entry_price
            mid_note = "no live mid (using entry)"
        else:
            leg = yes_mid if side == "YES" else (1.0 - yes_mid)
            mid_note = f"mark {leg:.4f}"
        mkt_value = shares * leg
        u_pnl = mkt_value - cost
        lines.append(
            f"• {_trim_slug(slug)}\n"
            f"  {side} · entry {entry_price:.4f} · {shares:.2f} sh · "
            f"cost ${cost:,.2f} · {mid_note}\n"
            f"  ~value ${mkt_value:,.2f} · uPnL ${u_pnl:+,.2f}"
        )
    return "\n".join(lines)


async def portfolio_summary_message(price_lookup):
    value = await estimate_portfolio_value(price_lookup)
    cash = await get_cash()
    positions = await get_open_positions()

    pnl = value - STARTING_VALUE
    pnl_pct = pnl / STARTING_VALUE * 100

    pos_block = await _format_positions_block(price_lookup, positions)

    return (
        f"📊 Portfolio Summary\n"
        f"Portfolio value: ${value:,.2f}\n"
        f"P/L: ${pnl:,.2f} ({pnl_pct:.2f}%)\n"
        f"Cash: ${cash:,.2f}\n"
        f"Active positions: {len(positions)}\n\n"
        f"{pos_block}"
    )


async def send_portfolio_summary(price_lookup):
    msg = await portfolio_summary_message(price_lookup)
    await send_alert(msg)


async def hourly_summary(price_lookup):
    while True:
        await send_portfolio_summary(price_lookup)
        await asyncio.sleep(3600)
