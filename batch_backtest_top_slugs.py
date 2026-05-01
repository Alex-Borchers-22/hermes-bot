#!/usr/bin/env python3
"""
Run the same backtest replay as `backtest.py` for the top-N markets by snapshot count.

Example:
  python batch_backtest_top_slugs.py
  python batch_backtest_top_slugs.py --top 20 --db paper_portfolio.db
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from dataclasses import dataclass

from backtest import load_snapshots, replay
from db import DB_PATH

STARTING_VALUE = 1000.0


def top_slugs_by_snapshots(db_path: str, limit: int) -> list[tuple[str, int]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT slug, COUNT(*) AS n
            FROM market_snapshots
            GROUP BY slug
            ORDER BY n DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [(str(r[0]), int(r[1])) for r in cur.fetchall()]
    finally:
        conn.close()


@dataclass
class RowResult:
    rank: int
    slug: str
    snapshots: int
    ticks: int
    buys: int
    sells: int
    final_pv: float
    pnl: float
    open_summary: str


async def backtest_slug(db_path: str, slug: str, topic: str) -> dict | None:
    snaps = await load_snapshots(db_path, slug)
    if not snaps:
        return None
    stats = replay(slug, topic, snaps, verbose=False)
    stats["slug"] = slug
    return stats


async def run_all(db_path: str, slugs: list[tuple[str, int]], topic: str) -> list[RowResult]:
    tasks = [backtest_slug(db_path, slug, topic) for slug, _ in slugs]
    outcomes = await asyncio.gather(*tasks)
    rows: list[RowResult] = []
    for rank, ((slug, snap_count), stats) in enumerate(zip(slugs, outcomes), start=1):
        if stats is None:
            rows.append(
                RowResult(
                    rank=rank,
                    slug=slug,
                    snapshots=snap_count,
                    ticks=0,
                    buys=0,
                    sells=0,
                    final_pv=float("nan"),
                    pnl=float("nan"),
                    open_summary="(no snapshots)",
                )
            )
            continue
        op = stats["open_position"]
        if op:
            open_summary = f"{op.side} @ {op.entry_price:.3f} ({op.shares:.4f} sh)"
        else:
            open_summary = "-"
        final_pv = float(stats["final_portfolio_value"])
        rows.append(
            RowResult(
                rank=rank,
                slug=slug,
                snapshots=snap_count,
                ticks=int(stats["ticks"]),
                buys=int(stats["buys"]),
                sells=int(stats["sells"]),
                final_pv=final_pv,
                pnl=final_pv - STARTING_VALUE,
                open_summary=open_summary,
            )
        )
    return rows


def print_report(rows: list[RowResult]) -> None:
    w_rank, w_ticks, w_buys, w_sells = 4, 6, 5, 5
    w_pnl, w_pv = 12, 12
    slug_w = max(len("slug"), max((len(r.slug) for r in rows), default=10), 50)

    def line(
        rank: str,
        slug: str,
        ticks: str,
        buys: str,
        sells: str,
        pv: str,
        pnl: str,
        op: str,
    ) -> str:
        slug_disp = slug if len(slug) <= slug_w else slug[: slug_w - 3] + "..."
        return (
            f"{rank:>{w_rank}}  {slug_disp:<{slug_w}}  "
            f"{ticks:>{w_ticks}}  {buys:>{w_buys}}  {sells:>{w_sells}}  "
            f"{pv:>{w_pv}}  {pnl:>{w_pnl}}  {op}"
        )

    header = line("#", "slug", "ticks", "buys", "sells", "final_pv", "pnl", "open")
    print(header)
    print("-" * len(header))
    for r in rows:
        if r.ticks == 0:
            print(
                line(
                    str(r.rank),
                    r.slug,
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    r.open_summary,
                )
            )
        else:
            print(
                line(
                    str(r.rank),
                    r.slug,
                    str(r.ticks),
                    str(r.buys),
                    str(r.sells),
                    f"${r.final_pv:.2f}",
                    f"${r.pnl:+.2f}",
                    r.open_summary,
                )
            )

    ok = [r for r in rows if r.ticks > 0]
    if not ok:
        return
    total_buys = sum(r.buys for r in ok)
    total_sells = sum(r.sells for r in ok)
    mean_pnl = sum(r.pnl for r in ok) / len(ok)
    best = max(ok, key=lambda r: r.pnl)
    worst = min(ok, key=lambda r: r.pnl)
    print()
    print(
        f"Markets with data: {len(ok)} / {len(rows)}  |  "
        f"total buys={total_buys}  total sells={total_sells}  |  "
        f"mean P/L vs ${STARTING_VALUE:.0f} start: ${mean_pnl:+.2f}"
    )
    print(f"Best P/L:  ${best.pnl:+.2f}  ({best.slug})")
    print(f"Worst P/L: ${worst.pnl:+.2f}  ({worst.slug})")


async def _async_main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=DB_PATH, help=f"SQLite path (default: {DB_PATH})")
    p.add_argument("--top", type=int, default=20, help="How many slugs by snapshot count (default: 20)")
    p.add_argument(
        "--topic",
        default="backtest",
        help="Topic label for per-topic caps inside replay (default: backtest)",
    )
    args = p.parse_args()

    slugs = top_slugs_by_snapshots(args.db, args.top)
    if not slugs:
        print(f"No rows in market_snapshots for {args.db!r}", file=sys.stderr)
        return 1

    rows = await run_all(args.db, slugs, args.topic)
    print_report(rows)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
