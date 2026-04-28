import asyncio
import logging
from datetime import datetime, timezone

import httpx
from db import init_db
from markets import load_candidate_markets
from portfolio import (
    count_open_positions,
    estimate_portfolio_value,
    get_open_position_by_slug,
    paper_buy,
    paper_sell,
)
from snapshot import MarketSnapshot, fetch_snapshot, diff
from alerts import send_alert
from summary import hourly_summary, send_portfolio_summary
from strategy import (
    BUY_MIN_IMBALANCE,
    BUY_MIN_PRICE_DELTA,
    CANDIDATE_MARKETS_MAX,
    CANDIDATE_MARKETS_MIN,
    MAX_OPEN_POSITIONS,
    MAX_POSITIONS_PER_TOPIC,
    MAX_SPREAD,
    SIGNAL_CONFIRM_TICKS,
)

TICK = 60

# Exit open positions when marked price moves this far vs entry (paper demo defaults).
EXIT_TAKE_PROFIT_MULT = 1.12
EXIT_STOP_LOSS_MULT = 0.88

latest_prices = {}


async def get_current_price(slug: str) -> float | None:
    return latest_prices.get(slug)


async def monitor(
    slug: str,
    state: dict,
    client: httpx.AsyncClient,
    topic: str,
):
    previous: MarketSnapshot | None = None

    while True:
        try:
            current = await fetch_snapshot(client, slug)
            latest_prices[slug] = current.yes_price

            pos = await get_open_position_by_slug(slug)
            if pos:
                state["yes_streak"] = 0
                state["no_streak"] = 0
                _, _, side, entry_price, _shares, _cost, _, _t = pos
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

            elif previous:
                d = diff(previous, current)

                if current.spread > MAX_SPREAD:
                    state["yes_streak"] = 0
                    state["no_streak"] = 0
                else:
                    if (
                        d["imbalance"] > BUY_MIN_IMBALANCE
                        and d["price_delta"] > BUY_MIN_PRICE_DELTA
                    ):
                        state["yes_streak"] += 1
                    else:
                        state["yes_streak"] = 0

                    if (
                        d["imbalance"] < -BUY_MIN_IMBALANCE
                        and d["price_delta"] < -BUY_MIN_PRICE_DELTA
                    ):
                        state["no_streak"] += 1
                    else:
                        state["no_streak"] = 0

                    if state["yes_streak"] == SIGNAL_CONFIRM_TICKS:
                        portfolio_value = await estimate_portfolio_value(
                            get_current_price
                        )
                        bought, buy_msg = await paper_buy(
                            slug=slug,
                            side="YES",
                            price=current.yes_price,
                            portfolio_value=portfolio_value,
                            reason=(
                                f"imbalance={d['imbalance']:.2f}, "
                                f"price_delta={d['price_delta']:.3f}, "
                                f"{SIGNAL_CONFIRM_TICKS}× confirm YES"
                            ),
                            topic=topic,
                        )
                        state["yes_streak"] = 0
                        state["no_streak"] = 0
                        if bought:
                            await send_alert(f"🧪 PAPER BUY\n{buy_msg}")
                            await send_portfolio_summary(get_current_price)

                    elif state["no_streak"] == SIGNAL_CONFIRM_TICKS:
                        portfolio_value = await estimate_portfolio_value(
                            get_current_price
                        )
                        bought, buy_msg = await paper_buy(
                            slug=slug,
                            side="NO",
                            price=1.0 - current.yes_price,
                            portfolio_value=portfolio_value,
                            reason=(
                                f"imbalance={d['imbalance']:.2f}, "
                                f"price_delta={d['price_delta']:.3f}, "
                                f"{SIGNAL_CONFIRM_TICKS}× confirm NO"
                            ),
                            topic=topic,
                        )
                        state["yes_streak"] = 0
                        state["no_streak"] = 0
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
        candidates = await load_candidate_markets(client)
        if not candidates:
            raise SystemExit(
                "No candidate markets after Gamma filters; relax criteria or try later."
            )

        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        n_open = await count_open_positions()
        logging.info(
            "Hermes bot running — %d candidate markets (target %d–%d), tick=%ds, "
            "open positions %d/%d, imbalance>%s |Δprice|>%s spread≤%s confirm=%d tick(s)",
            len(candidates),
            CANDIDATE_MARKETS_MIN,
            CANDIDATE_MARKETS_MAX,
            TICK,
            n_open,
            MAX_OPEN_POSITIONS,
            BUY_MIN_IMBALANCE,
            BUY_MIN_PRICE_DELTA,
            MAX_SPREAD,
            SIGNAL_CONFIRM_TICKS,
        )

        states = {
            slug: {"yes_streak": 0, "no_streak": 0}
            for slug, _topic in candidates
        }

        await send_alert(
            f"✅ Hermes bot started\n"
            f"Time (UTC): {started_at}\n"
            f"Candidates: {len(candidates)} markets ({CANDIDATE_MARKETS_MIN}–{CANDIDATE_MARKETS_MAX})\n"
            f"Tick: {TICK}s\n"
            f"Portfolio cap: {MAX_OPEN_POSITIONS} open; "
            f"max {MAX_POSITIONS_PER_TOPIC} per topic (see strategy.py)\n"
            f"Signal: imbalance>{BUY_MIN_IMBALANCE}, "
            f"|Δprice|>{BUY_MIN_PRICE_DELTA}, spread≤{MAX_SPREAD}, "
            f"{SIGNAL_CONFIRM_TICKS} consecutive ticks"
        )

        await asyncio.gather(
            *[
                monitor(slug, states[slug], client, topic)
                for slug, topic in candidates
            ],
            hourly_summary(get_current_price),
        )


if __name__ == "__main__":
    asyncio.run(main())