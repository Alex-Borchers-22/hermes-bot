"""
Replay stored market_snapshots against the same signal + exit rules as main.monitor.

Uses an in-memory portfolio so the live paper_portfolio.db is unchanged.

Example:
  python backtest.py --slug your-market-slug
  python backtest.py --slug your-market-slug --db path/to/paper_portfolio.db
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

import aiosqlite

from db import DB_PATH
from portfolio import position_pct_from_performance
from snapshot import MarketSnapshot, diff
from strategy import (
    BUY_MIN_IMBALANCE,
    BUY_MIN_PRICE_DELTA,
    EXIT_STOP_LOSS_MULT,
    EXIT_TAKE_PROFIT_MULT,
    MAX_OPEN_POSITIONS,
    MAX_POSITIONS_PER_TOPIC,
    MAX_SPREAD,
    SIGNAL_CONFIRM_TICKS,
)


@dataclass
class _SimPosition:
    slug: str
    side: str
    entry_price: float
    shares: float
    cost: float
    topic: str


class SimPortfolio:
    """Minimal mirror of paper_buy / paper_sell constraints (sync, in-memory)."""

    def __init__(self, starting_cash: float = 1000.0) -> None:
        self.cash = starting_cash
        self.starting_value = starting_cash
        self._by_slug: dict[str, _SimPosition] = {}

    def _count_open(self) -> int:
        return len(self._by_slug)

    def _count_topic(self, topic: str) -> int:
        return sum(1 for p in self._by_slug.values() if p.topic == topic)

    def estimate_value(self, yes_by_slug: dict[str, float]) -> float:
        """Match portfolio.estimate_portfolio_value: unrealized uses yes mid per slug."""
        unrealized = 0.0
        for slug, pos in self._by_slug.items():
            y = yes_by_slug.get(slug)
            if y is None:
                y = pos.entry_price if pos.side == "YES" else (1.0 - pos.entry_price)
            unrealized += pos.shares * y
        return self.cash + unrealized

    def get_open(self, slug: str) -> _SimPosition | None:
        return self._by_slug.get(slug)

    def try_buy(
        self,
        slug: str,
        side: str,
        price: float,
        yes_by_slug: dict[str, float],
        topic: str,
    ) -> tuple[bool, str]:
        if slug in self._by_slug:
            return False, "Already holding"

        if self._count_open() >= MAX_OPEN_POSITIONS:
            return False, "Max open positions"

        if self._count_topic(topic) >= MAX_POSITIONS_PER_TOPIC:
            return False, "Max positions for topic"

        pv = self.estimate_value(yes_by_slug)
        pct = position_pct_from_performance(pv, self.starting_value)
        notional = min(pv * pct, self.cash)

        if notional < 5:
            return False, "Not enough cash"

        shares = notional / price
        self._by_slug[slug] = _SimPosition(
            slug=slug,
            side=side,
            entry_price=price,
            shares=shares,
            cost=notional,
            topic=topic,
        )
        self.cash -= notional
        return True, f"Bought ${notional:.2f} {side} at {price:.3f}"

    def try_sell(
        self,
        slug: str,
        exit_price: float,
        yes_by_slug: dict[str, float],
    ) -> tuple[bool, str]:
        pos = self._by_slug.get(slug)
        if not pos:
            return False, "No open position"

        proceeds = pos.shares * exit_price
        realized = proceeds - pos.cost
        del self._by_slug[slug]
        self.cash += proceeds
        return True, f"Sold ${proceeds:.2f} ({pos.side}) at {exit_price:.3f} P/L ${realized:+,.2f}"


async def load_snapshots(db_path: str, slug: str) -> list[MarketSnapshot]:
    async with aiosqlite.connect(db_path) as db:
        rows = await db.execute_fetchall(
            """
            SELECT slug, yes_price, bid_size, ask_size, spread
            FROM market_snapshots
            WHERE slug = ?
            ORDER BY ts
            """,
            (slug,),
        )
    return [
        MarketSnapshot(
            slug=r[0],
            ts=0.0,
            yes_price=float(r[1]),
            bid_size=float(r[2]),
            ask_size=float(r[3]),
            spread=float(r[4]),
        )
        for r in rows
    ]


def replay(
    slug: str,
    topic: str,
    snapshots: list[MarketSnapshot],
    verbose: bool = False,
) -> dict:
    """Walk snapshots with the same streak / TP-SL logic as main.monitor."""
    port = SimPortfolio()
    state = {"yes_streak": 0, "no_streak": 0}
    previous: MarketSnapshot | None = None
    yes_prices: dict[str, float] = {}
    buys = sells = 0

    for current in snapshots:
        yes_prices[slug] = current.yes_price

        pos = port.get_open(slug)
        if pos:
            state["yes_streak"] = 0
            state["no_streak"] = 0
            mark = (
                current.yes_price
                if pos.side == "YES"
                else (1.0 - current.yes_price)
            )
            tp_hit = mark >= pos.entry_price * EXIT_TAKE_PROFIT_MULT
            sl_hit = mark <= pos.entry_price * EXIT_STOP_LOSS_MULT
            if tp_hit or sl_hit:
                ok, msg = port.try_sell(slug, mark, yes_prices)
                if ok:
                    sells += 1
                    if verbose:
                        print(f"SELL {msg}")

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
                    ok, msg = port.try_buy(
                        slug,
                        "YES",
                        current.yes_price,
                        yes_prices,
                        topic,
                    )
                    state["yes_streak"] = 0
                    state["no_streak"] = 0
                    if ok:
                        buys += 1
                        if verbose:
                            print(f"BUY  {msg}")

                elif state["no_streak"] == SIGNAL_CONFIRM_TICKS:
                    ok, msg = port.try_buy(
                        slug,
                        "NO",
                        1.0 - current.yes_price,
                        yes_prices,
                        topic,
                    )
                    state["yes_streak"] = 0
                    state["no_streak"] = 0
                    if ok:
                        buys += 1
                        if verbose:
                            print(f"BUY  {msg}")

        previous = current

    final_pv = port.estimate_value({slug: snapshots[-1].yes_price} if snapshots else {})
    return {
        "ticks": len(snapshots),
        "buys": buys,
        "sells": sells,
        "final_cash": port.cash,
        "final_portfolio_value": final_pv,
        "open_position": port.get_open(slug),
    }


async def _run():
    p = argparse.ArgumentParser(description="Backtest from SQLite market_snapshots")
    p.add_argument("--slug", required=True, help="Market slug (must match stored rows)")
    p.add_argument(
        "--topic",
        default="backtest",
        help="Topic label for per-topic position caps (default: backtest)",
    )
    p.add_argument("--db", default=DB_PATH, help=f"SQLite path (default: {DB_PATH})")
    p.add_argument("-v", "--verbose", action="store_true", help="Print each simulated trade")
    args = p.parse_args()

    snaps = await load_snapshots(args.db, args.slug)
    if not snaps:
        print(f"No snapshots for slug={args.slug!r} in {args.db}")
        return

    stats = replay(args.slug, args.topic, snaps, verbose=args.verbose)
    print(
        f"slug={args.slug!r} ticks={stats['ticks']} "
        f"buys={stats['buys']} sells={stats['sells']} "
        f"final_pv=${stats['final_portfolio_value']:.2f} cash=${stats['final_cash']:.2f}"
    )
    if stats["open_position"]:
        op = stats["open_position"]
        print(f"Still open: {op.side} @ {op.entry_price:.3f} ({op.shares:.4f} sh)")


if __name__ == "__main__":
    asyncio.run(_run())
