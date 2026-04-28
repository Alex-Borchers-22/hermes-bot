import asyncio
import logging
from datetime import datetime, timezone

import httpx
from db import init_db
from portfolio import (
    estimate_portfolio_value,
    get_open_position_by_slug,
    paper_buy,
    paper_sell,
)
from snapshot import fetch_snapshot, diff
from alerts import send_alert
from summary import hourly_summary, send_portfolio_summary

GAMMA = "https://gamma-api.polymarket.com"

TICK = 60

# Paper buy: both must hold vs prior tick (see README). Loosened slightly for more fills.
BUY_MIN_IMBALANCE = 0.55
BUY_MIN_PRICE_DELTA = 0.015

# Exit open positions when marked price moves this far vs entry (paper demo defaults).
EXIT_TAKE_PROFIT_MULT = 1.12
EXIT_STOP_LOSS_MULT = 0.88

latest_prices = {}


async def get_top_market_slugs(client: httpx.AsyncClient, limit: int = 10) -> list[str]:
    r = await client.get(
        f"{GAMMA}/markets",
        params={
            "closed": "false",
            "order": "volume_24hr",
            "ascending": "false",
            "limit": str(limit),
        },
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return []
    return [m["slug"] for m in data if m.get("slug")]


async def get_current_price(slug: str) -> float | None:
    return latest_prices.get(slug)


async def monitor(slug: str, _state: dict, client: httpx.AsyncClient):
    previous: MarketSnapshot | None = None

    while True:
        try:
            current = await fetch_snapshot(client, slug)
            latest_prices[slug] = current.yes_price

            pos = await get_open_position_by_slug(slug)
            if pos:
                _, _, side, entry_price, _shares, _cost, _ = pos
                mark = (
                    current.yes_price
                    if side == "YES"
                    else (1.0 - current.yes_price)
                )
                tp_hit = mark >= entry_price * EXIT_TAKE_PROFIT_MULT
                sl_hit = mark <= entry_price * EXIT_STOP_LOSS_MULT
                if tp_hit or sl_hit:
                    portfolio_value = await estimate_portfolio_value(
                        get_current_price
                    )
                    reason = (
                        f"take-profit (>={EXIT_TAKE_PROFIT_MULT:.2f}× entry)"
                        if tp_hit
                        else f"stop-loss (<={EXIT_STOP_LOSS_MULT:.2f}× entry)"
                    )
                    sold, sell_msg = await paper_sell(
                        slug,
                        mark,
                        portfolio_value,
                        reason,
                    )
                    if sold:
                        await send_alert(f"🧪 PAPER SELL\n{sell_msg}")
                        await send_portfolio_summary(get_current_price)

            if previous:
                d = diff(previous, current)

                if (
                    abs(d["imbalance"]) > BUY_MIN_IMBALANCE
                    and abs(d["price_delta"]) > BUY_MIN_PRICE_DELTA
                ):
                    side = "YES" if d["imbalance"] > 0 else "NO"
                    price = current.yes_price if side == "YES" else (1.0 - current.yes_price)
                    portfolio_value = await estimate_portfolio_value(get_current_price)
                    bought, buy_msg = await paper_buy(
                        slug=slug,
                        side=side,
                        price=price,
                        portfolio_value=portfolio_value,
                        reason=(
                            f"imbalance={d['imbalance']:.2f}, "
                            f"price_delta={d['price_delta']:.3f}"
                        ),
                    )
                    if bought:
                        await send_alert(f"🧪 PAPER BUY\n{buy_msg}")
                        await send_portfolio_summary(get_current_price)

            previous = current

        except Exception as e:
            print(f"[{slug}] error: {e}")

        await asyncio.sleep(TICK)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    await init_db()

    async with httpx.AsyncClient(timeout=15) as client:
        markets = await get_top_market_slugs(client, limit=10)
        if not markets:
            raise SystemExit("No markets returned from Gamma; check API or try again later.")

        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logging.info(
            "Hermes bot running — %d markets, tick=%ds, buy thresholds imbalance>%s price_delta>%s",
            len(markets),
            TICK,
            BUY_MIN_IMBALANCE,
            BUY_MIN_PRICE_DELTA,
        )

        await send_alert(
            f"✅ Hermes bot started\n"
            f"Time (UTC): {started_at}\n"
            f"Markets: {len(markets)} (top volume)\n"
            f"Tick: {TICK}s\n"
            f"Buy when imbalance>{BUY_MIN_IMBALANCE} and |price_delta|>{BUY_MIN_PRICE_DELTA}"
        )

        states = {s: {} for s in markets}

        await asyncio.gather(
            *[monitor(slug, states[slug], client) for slug in markets],
            hourly_summary(get_current_price),
        )


if __name__ == "__main__":
    asyncio.run(main())
