#!/usr/bin/env python3
"""Backfill Gamma condition_id and/or Polygon settlement coordinates for open positions."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portfolio import (  # noqa: E402
    update_open_position_condition_id,
    update_open_position_settlement_chain,
)


async def _run() -> int:
    p = argparse.ArgumentParser(
        description="Update open position metadata for settlement polling."
    )
    p.add_argument("--slug", required=True, help="Market slug (positions.slug)")
    p.add_argument(
        "--condition-id",
        dest="condition_id",
        default=None,
        help="Gamma conditionId (hex string from API / UI)",
    )
    p.add_argument(
        "--settlement-tx",
        dest="settlement_tx",
        default=None,
        help="Polygon tx hash for optional chain fallback decode",
    )
    p.add_argument(
        "--log-index",
        dest="log_index",
        type=int,
        default=None,
        help="Global log index inside the receipt (oracle settled page event index)",
    )
    args = p.parse_args()

    if args.settlement_tx is not None and args.log_index is None:
        print("--log-index is required with --settlement-tx.", file=sys.stderr)
        return 1
    if args.log_index is not None and args.settlement_tx is None:
        print("--settlement-tx is required with --log-index.", file=sys.stderr)
        return 1

    if not args.condition_id and args.settlement_tx is None:
        print(
            "Provide --condition-id and/or --settlement-tx with --log-index.",
            file=sys.stderr,
        )
        return 1

    if args.condition_id:
        n = await update_open_position_condition_id(args.slug, args.condition_id)
        print(f"Updated condition_id for open slug={args.slug!r} ({n} row(s)).")

    if args.settlement_tx is not None and args.log_index is not None:
        m = await update_open_position_settlement_chain(
            args.slug,
            args.settlement_tx,
            args.log_index,
        )
        print(f"Updated settlement tx/log for open slug={args.slug!r} ({m} row(s)).")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
