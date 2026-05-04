import json
import time
from dataclasses import dataclass

import httpx

from gamma_market import fetch_gamma_market, parse_yes_from_outcome_prices

CLOB = "https://clob.polymarket.com"

# If CLOB mid is degenerate (empty book → 0/1) or spread ~1, prefer Gamma outcomePrices.
_DEGENERATE_SPREAD_THRESHOLD = 0.95


def _clob_token_ids(market: dict) -> list[str]:
    """Gamma often returns clobTokenIds as a JSON-encoded string, not a list."""
    raw = market.get("clobTokenIds")
    if raw is None:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return list(raw)


@dataclass
class MarketSnapshot:
    slug: str
    ts: float
    yes_price: float
    bid_size: float
    ask_size: float
    spread: float


async def fetch_snapshot(
    client: httpx.AsyncClient,
    slug: str,
    *,
    market: dict | None = None,
) -> MarketSnapshot:
    if market is None:
        market = await fetch_gamma_market(client, slug)
        if not market:
            raise ValueError(f"No market found for slug: {slug}")

    token_ids = _clob_token_ids(market)
    if not token_ids:
        raise ValueError(f"No clobTokenIds for slug: {slug}")

    token_id = token_ids[0]

    book = (await client.get(f"{CLOB}/book?token_id={token_id}")).json()

    bids = book.get("bids", [])
    asks = book.get("asks", [])

    best_bid = float(bids[0]["price"]) if bids else 0.0
    best_ask = float(asks[0]["price"]) if asks else 1.0

    bid_size = sum(float(b["size"]) for b in bids[:5])
    ask_size = sum(float(a["size"]) for a in asks[:5])

    spread = best_ask - best_bid
    yes_mid = (best_bid + best_ask) / 2.0

    gamma_yes = parse_yes_from_outcome_prices(market)
    if gamma_yes is not None:
        if not bids and not asks:
            yes_mid = gamma_yes
            spread = 0.0
        elif spread >= _DEGENERATE_SPREAD_THRESHOLD:
            yes_mid = gamma_yes
            spread = min(spread, 0.5)

    return MarketSnapshot(
        slug=slug,
        ts=time.time(),
        yes_price=yes_mid,
        bid_size=bid_size,
        ask_size=ask_size,
        spread=spread,
    )


def diff(prev: MarketSnapshot, curr: MarketSnapshot) -> dict:
    return {
        "price_delta": curr.yes_price - prev.yes_price,
        "bid_delta": curr.bid_size - prev.bid_size,
        "ask_delta": curr.ask_size - prev.ask_size,
        "imbalance": (curr.bid_size - curr.ask_size)
        / max(curr.bid_size + curr.ask_size, 1),
    }