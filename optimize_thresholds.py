#!/usr/bin/env python3
"""
Random search over replay thresholds to maximize paper P/L on a fixed snapshot corpus.

Each trial runs an isolated $1k replay per slug (same semantics as batch_backtest_top_slugs).
Objective default: sum of (final_portfolio_value - 1000) across slugs.

Example:
  python optimize_thresholds.py --samples 400 --top 20 --seed 42
  python optimize_thresholds.py --db paper_portfolio.db --samples 2000 --min-total-buys 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from dataclasses import asdict

from batch_backtest_top_slugs import top_slugs_by_snapshots
from backtest import ReplayParams, load_snapshots, replay
from db import DB_PATH

STARTING = 1000.0


def sample_replay_params(rng: random.Random) -> ReplayParams:
    """Uniform-random knobs; ranges match wide spreads + tiny minute-to-minute mids in SQLite."""
    imb = rng.uniform(0.18, 0.55)
    dpx = rng.uniform(0.00015, 0.006)
    spr = rng.uniform(0.35, 1.0)
    ticks = rng.randint(1, 3)
    tp = rng.uniform(1.03, 1.28)
    sl = rng.uniform(0.72, 0.96)
    if sl >= tp:
        sl = min(sl, tp - 0.05)
    if sl >= 0.999:
        sl = 0.95
    if tp <= 1.001:
        tp = 1.05
    return ReplayParams(
        buy_min_imbalance=round(imb, 4),
        buy_min_price_delta=round(dpx, 5),
        max_spread=round(spr, 4),
        signal_confirm_ticks=ticks,
        exit_take_profit_mult=round(tp, 4),
        exit_stop_loss_mult=round(sl, 4),
    )


def evaluate_corpus(
    params: ReplayParams,
    corpus: list[tuple[str, list]],
    *,
    min_total_buys: int,
    objective: str,
) -> dict:
    total_pnl = 0.0
    total_buys = 0
    total_sells = 0
    n = 0
    for slug, snaps in corpus:
        if not snaps:
            continue
        n += 1
        st = replay(slug, "backtest", snaps, verbose=False, params=params)
        total_pnl += float(st["final_portfolio_value"]) - STARTING
        total_buys += int(st["buys"])
        total_sells += int(st["sells"])

    if n == 0:
        score = float("-inf")
    elif total_buys < min_total_buys:
        score = float("-inf")
    elif objective == "mean_pnl":
        score = total_pnl / n
    else:
        score = total_pnl

    return {
        "score": score,
        "total_pnl": total_pnl,
        "mean_pnl": total_pnl / n if n else float("nan"),
        "total_buys": total_buys,
        "total_sells": total_sells,
        "slugs": n,
    }


async def load_corpus(db_path: str, top: int) -> list[tuple[str, list]]:
    slugs = top_slugs_by_snapshots(db_path, top)
    out: list[tuple[str, list]] = []
    for slug, _n in slugs:
        snaps = await load_snapshots(db_path, slug)
        out.append((slug, snaps))
    return out


async def _async_main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DB_PATH, help=f"SQLite path (default: {DB_PATH})")
    ap.add_argument("--top", type=int, default=20, help="Top slugs by snapshot count (default: 20)")
    ap.add_argument("--samples", type=int, default=500, help="Random parameter draws (default: 500)")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed (default: nondeterministic)")
    ap.add_argument(
        "--min-total-buys",
        type=int,
        default=0,
        help="Reject trials with fewer total buys across all slugs (default: 0). "
        "Set e.g. 5 to ignore flat no-trade parameter sets.",
    )
    ap.add_argument(
        "--objective",
        choices=("sum_pnl", "mean_pnl"),
        default="sum_pnl",
        help="sum_pnl: sum of per-slug P/L; mean_pnl: average per slug (default: sum_pnl)",
    )
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="Also score current strategy.ReplayParams() defaults",
    )
    ap.add_argument("--top-k", type=int, default=5, help="Print this many best trials (default: 5)")
    args = ap.parse_args()

    rng = random.Random(args.seed)

    t0 = time.perf_counter()
    corpus = await load_corpus(args.db, args.top)
    load_s = time.perf_counter() - t0
    nonempty = sum(1 for _, s in corpus if s)
    if nonempty == 0:
        print(f"No snapshot data in top {args.top} slugs for {args.db!r}", file=sys.stderr)
        return 1

    results: list[tuple[float, ReplayParams, dict]] = []

    if args.baseline:
        bp = ReplayParams()
        ev = evaluate_corpus(bp, corpus, min_total_buys=args.min_total_buys, objective=args.objective)
        results.append((ev["score"], bp, ev))
        print(f"Baseline strategy defaults: score={ev['score']:.4f}  {json.dumps({k: ev[k] for k in ev if k != 'score'}, indent=2)}")
        print()

    t1 = time.perf_counter()
    for i in range(args.samples):
        params = sample_replay_params(rng)
        ev = evaluate_corpus(params, corpus, min_total_buys=args.min_total_buys, objective=args.objective)
        results.append((ev["score"], params, ev))
        if (i + 1) % max(1, args.samples // 10) == 0 or i == 0:
            elapsed = time.perf_counter() - t1
            print(f"  progress {i + 1}/{args.samples}  elapsed {elapsed:.1f}s", flush=True)

    search_s = time.perf_counter() - t1
    results.sort(
        key=lambda x: (x[0], x[2]["total_buys"] + x[2]["total_sells"], x[2]["total_pnl"]),
        reverse=True,
    )
    finite = [r for r in results if r[0] > float("-inf")]
    print()
    print(f"Corpus: top {args.top} slugs, {nonempty} with snapshots  |  load {load_s:.2f}s  |  search {search_s:.2f}s")
    print(f"Objective: {args.objective}  |  min_total_buys={args.min_total_buys}  |  trials={len(results)}")
    if not finite:
        print("No trial satisfied min_total_buys; try --min-total-buys 0 or more --samples.")
        return 2

    k = min(args.top_k, len(finite))
    print(f"\nBest {k} parameter sets:\n")
    for rank, (score, params, ev) in enumerate(finite[:k], start=1):
        print(f"--- #{rank}  score={score:.4f}  total_pnl=${ev['total_pnl']:.2f}  mean_pnl=${ev['mean_pnl']:.4f}  buys={ev['total_buys']} sells={ev['total_sells']} ---")
        print(json.dumps(asdict(params), indent=2))
        print()

    best_score, best_params, best_ev = finite[0]
    print("Suggested ReplayParams (best trial). If you adopt them, mirror values into strategy.py:")
    print(json.dumps(asdict(best_params), indent=2))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
