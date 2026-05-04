"""Gamma API helpers: fetch market by slug, settlement detection, outcome prices."""

from __future__ import annotations

import json

import httpx

GAMMA = "https://gamma-api.polymarket.com"


async def fetch_gamma_market(client: httpx.AsyncClient, slug: str) -> dict | None:
    markets = (await client.get(f"{GAMMA}/markets?slug={slug}")).json()
    return markets[0] if markets else None


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
