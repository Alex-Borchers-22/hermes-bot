"""Gamma API helpers: fetch market by slug, settlement detection, outcome prices."""

from __future__ import annotations

import json
from typing import Any

import httpx

GAMMA = "https://gamma-api.polymarket.com"


def _first_market(payload: Any) -> dict | None:
    if isinstance(payload, list) and payload:
        return payload[0]
    return None


async def _get_markets(
    client: httpx.AsyncClient,
    params: list[tuple[str, str]] | None = None,
) -> dict | None:
    """Gamma accepts repeated keys for array params (e.g. condition_ids)."""
    r = await client.get(f"{GAMMA}/markets", params=params)
    r.raise_for_status()
    return _first_market(r.json())


async def fetch_gamma_market(
    client: httpx.AsyncClient,
    slug: str,
    *,
    condition_id: str | None = None,
) -> dict | None:
    """
    Resolve a market dict from Gamma.

    Default list filters exclude closed markets (closed defaults false). After resolution,
    slug-only queries can return []. We retry with closed=true and optionally by
    condition_ids (stable on-chain id persisted at buy time).
    """
    # 1) Active-style listing (matches historical bot behavior)
    m = await _get_markets(
        client,
        [("slug", slug), ("limit", "1")],
    )
    if m:
        return m

    # 2) Include closed markets (settled / delisted from default index)
    m = await _get_markets(
        client,
        [("slug", slug), ("closed", "true"), ("limit", "1")],
    )
    if m:
        return m

    # 3) Fallback: condition id (when slug no longer resolves but id is known)
    if condition_id:
        cid = str(condition_id).strip()
        if cid:
            m = await _get_markets(
                client,
                [("condition_ids", cid), ("closed", "true"), ("limit", "1")],
            )
            if m:
                return m
            m = await _get_markets(
                client,
                [("condition_ids", cid), ("limit", "1")],
            )
            if m:
                return m

    return None


def market_is_finished(market: dict) -> bool:
    if market.get("closed") is True:
        return True
    ao = market.get("acceptingOrders")
    if ao is None:
        ao = market.get("accepting_orders")
    if ao is False:
        return True
    return False


def parse_yes_from_outcome_prices(market: dict) -> float | None:
    """
    Parse YES-token probability from Gamma outcomePrices (binary: index 0 = YES).
    Field may be a JSON string or a list of strings/numbers.
    """
    raw = market.get("outcomePrices")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(raw, list):
        arr = raw
    else:
        return None
    if not arr:
        return None
    try:
        y = float(arr[0])
    except (TypeError, ValueError, IndexError):
        return None
    return max(0.0, min(1.0, y))


def settlement_yes_price(market: dict) -> float | None:
    """
    When the market is finished, return resolved YES price from outcomePrices.
    Returns None if not finished or prices missing.
    """
    if not market_is_finished(market):
        return None
    return parse_yes_from_outcome_prices(market)
