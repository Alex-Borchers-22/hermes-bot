"""Discover and diversify candidate markets from Gamma."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict

import httpx

from strategy import (
    CANDIDATE_MARKETS_MAX,
    CANDIDATE_MARKETS_MIN,
    MAX_CANDIDATES_PER_TOPIC,
    MIN_LIQUIDITY,
    MIN_MARKETS_PER_TOPIC,
    MIN_VOLUME_24HR,
)

GAMMA = "https://gamma-api.polymarket.com"

# Topics we diversify across (slug keys stored on positions / monitoring).
PRIMARY_TOPICS = (
    "entertainment",
    "crypto",
    "politics",
    "macro",
    "sports",
)


def _float_field(m: dict, *keys: str) -> float:
    for k in keys:
        v = m.get(k)
        if v is not None and v != "":
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def volume_24hr(m: dict) -> float:
    return _float_field(m, "volume24hr", "volume_24hr", "volume24Hr", "volumeNum")


def liquidity_usd(m: dict) -> float:
    return _float_field(m, "liquidity", "liquidityNum", "liquidityClob")


def passes_gamma_filters(m: dict) -> bool:
    if m.get("active") is not True:
        return False
    if m.get("closed") is True:
        return False
    accepting = m.get("acceptingOrders")
    if accepting is None:
        accepting = m.get("accepting_orders")
    if accepting is not True:
        return False
    orderbook = m.get("enableOrderBook")
    if orderbook is None:
        orderbook = m.get("enable_order_book")
    if orderbook is not True:
        return False
    if liquidity_usd(m) <= MIN_LIQUIDITY:
        return False
    if volume_24hr(m) <= MIN_VOLUME_24HR:
        return False
    slug = m.get("slug")
    return bool(slug)


def _tag_slugs(market: dict) -> list[str]:
    raw = market.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            s = item.get("slug") or item.get("label") or ""
            if s:
                out.append(str(s).lower())
        elif isinstance(item, str):
            out.append(item.lower())
    return out


def infer_topic(market: dict) -> str | None:
    """Map a market to one PRIMARY_TOPICS bucket using tags + question text."""
    blob = " ".join(_tag_slugs(market)).lower()
    blob += " " + (market.get("question") or "").lower()
    blob += " " + (market.get("groupItemTitle") or "").lower()

    rules: list[tuple[str, tuple[str, ...]]] = [
        ("crypto", ("crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "defi")),
        ("sports", ("sports", "nba", "nfl", "mlb", "soccer", "ufc", "nhl", "cbb", "cfb")),
        ("politics", ("politic", "election", "senate", "congress", "president", "trump")),
        (
            "macro",
            (
                "econom",
                "fed",
                "macro",
                "gdp",
                "inflation",
                "geopolitic",
                "trade",
                "rates",
                "treasury",
            ),
        ),
        (
            "entertainment",
            (
                "entertain",
                "movie",
                "music",
                "gta",
                "celebr",
                "pop-culture",
                "culture",
                "tv",
                "film",
            ),
        ),
    ]

    for topic, needles in rules:
        if any(n in blob for n in needles):
            return topic

    return None


async def _fetch_market_pages(
    client: httpx.AsyncClient,
    *,
    page_size: int = 150,
    max_pages: int = 25,
) -> list[dict]:
    """Paginate Gamma /markets until enough rows or empty page."""
    all_rows: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        r = await client.get(
            f"{GAMMA}/markets",
            params={
                "closed": "false",
                "active": "true",
                "order": "volume_24hr",
                "ascending": "false",
                "limit": str(page_size),
                "offset": str(offset),
            },
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return all_rows


def _bucket_by_topic(qualified: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for m in qualified:
        t = infer_topic(m)
        key = t if t in PRIMARY_TOPICS else "unclassified"
        buckets[key].append(m)
    for key in buckets:
        buckets[key].sort(key=volume_24hr, reverse=True)
    return buckets


def select_candidate_markets(rows: list[dict]) -> list[tuple[str, str]]:
    """
    Return [(slug, topic), ...] length in [CANDIDATE_MARKETS_MIN, CANDIDATE_MARKETS_MAX].

    Ensures at least MIN_MARKETS_PER_TOPIC from each PRIMARY_TOPICS bucket when possible,
    then fills toward CANDIDATE_MARKETS_MAX by global volume with a per-topic soft cap.
    """
    qualified = [m for m in rows if passes_gamma_filters(m)]
    if not qualified:
        return []

    buckets = _bucket_by_topic(qualified)
    picked: list[tuple[str, str]] = []
    seen: set[str] = set()
    topic_counts: Counter[str] = Counter()

    # Phase 1 — take top MIN_MARKETS_PER_TOPIC from each primary bucket (round-robin order)
    for round_idx in range(MIN_MARKETS_PER_TOPIC):
        for t in PRIMARY_TOPICS:
            if len(picked) >= CANDIDATE_MARKETS_MAX:
                break
            lst = buckets.get(t, [])
            if round_idx >= len(lst):
                continue
            m = lst[round_idx]
            slug = m["slug"]
            if slug in seen:
                continue
            picked.append((slug, t))
            seen.add(slug)
            topic_counts[t] += 1

    # Phase 2 — fill by global volume with per-topic cap + unclassified
    all_by_vol = sorted(qualified, key=volume_24hr, reverse=True)

    def can_take(topic: str) -> bool:
        return topic_counts[topic] < MAX_CANDIDATES_PER_TOPIC

    for m in all_by_vol:
        if len(picked) >= CANDIDATE_MARKETS_MAX:
            break
        slug = m["slug"]
        if slug in seen:
            continue
        t = infer_topic(m)
        topic = t if t in PRIMARY_TOPICS else "unclassified"
        if not can_take(topic):
            continue
        picked.append((slug, topic))
        seen.add(slug)
        topic_counts[topic] += 1

    # Phase 3 — if still under MIN count, relax topic cap
    if len(picked) < CANDIDATE_MARKETS_MIN:
        for m in all_by_vol:
            if len(picked) >= CANDIDATE_MARKETS_MIN:
                break
            slug = m["slug"]
            if slug in seen:
                continue
            t = infer_topic(m)
            topic = t if t in PRIMARY_TOPICS else "unclassified"
            picked.append((slug, topic))
            seen.add(slug)
            topic_counts[topic] += 1

    picked = picked[:CANDIDATE_MARKETS_MAX]

    if len(picked) < CANDIDATE_MARKETS_MIN:
        logging.warning(
            "Only %d candidate markets after filters (wanted %d–%d); "
            "criteria may be tight or tags sparse.",
            len(picked),
            CANDIDATE_MARKETS_MIN,
            CANDIDATE_MARKETS_MAX,
        )

    return picked


async def load_candidate_markets(client: httpx.AsyncClient) -> list[tuple[str, str]]:
    rows = await _fetch_market_pages(client)
    logging.info("Gamma returned %d raw markets before screening", len(rows))
    return select_candidate_markets(rows)
