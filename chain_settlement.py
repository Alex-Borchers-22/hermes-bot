"""
Optional Polygon settlement: decode YES probability from a transaction receipt log.

Used when Gamma no longer returns the market but UMA/CTF settlement exists on-chain.
Set POLYGON_RPC_URL (or POLYGON_RPC). Requires positions.settlement_tx_hash and
settlement_log_index (global log index in the receipt).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

try:
    from eth_abi import decode as eth_abi_decode
except ImportError:
    eth_abi_decode = None  # type: ignore[misc, assignment]

try:
    from web3 import Web3
except ImportError:
    Web3 = None  # type: ignore[misc, assignment]


def _polygon_rpc_url() -> str | None:
    return os.environ.get("POLYGON_RPC_URL") or os.environ.get("POLYGON_RPC")


@lru_cache(maxsize=1)
def _condition_resolution_topic0() -> bytes:
    if Web3 is None:
        raise RuntimeError("web3 is required for chain settlement")
    sig = "ConditionResolution(bytes32,address,bytes32,uint256,uint256[])"
    return bytes(Web3.keccak(text=sig))


def _decode_condition_resolution_data(data_hex: str) -> float | None:
    """Binary market: YES payout ratio = payoutNumerators[0] / sum(payoutNumerators)."""
    if eth_abi_decode is None or not data_hex or data_hex == "0x":
        return None
    raw = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
    try:
        _slot_count, payouts = eth_abi_decode(["uint256", "uint256[]"], raw)
    except Exception:
        return None
    if not payouts or len(payouts) < 2:
        return None
    total = sum(int(x) for x in payouts)
    if total <= 0:
        return None
    return max(0.0, min(1.0, float(payouts[0]) / float(total)))


def _topic0_matches(log: dict[str, Any], expected: bytes) -> bool:
    topics = log.get("topics")
    if not topics:
        return False
    t0 = topics[0]
    try:
        t0b = bytes(t0)
    except Exception:
        return False
    return t0b == expected


def yes_price_from_chain_receipt(tx_hash: str, log_index: int) -> float | None:
    """
    Return resolved YES probability (0..1) from a CTF ConditionResolution-style log,
    or None if RPC/decode unavailable or log does not match expected signature.
    """
    if Web3 is None or eth_abi_decode is None:
        return None
    rpc = _polygon_rpc_url()
    if not rpc:
        return None
    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        return None
    h = tx_hash.strip()
    if not h.startswith("0x"):
        h = "0x" + h
    receipt = w3.eth.get_transaction_receipt(h)
    if receipt is None:
        return None
    logs = receipt.get("logs") or []
    if log_index < 0 or log_index >= len(logs):
        return None
    log = dict(logs[log_index])
    try:
        expected = _condition_resolution_topic0()
    except RuntimeError:
        return None
    if not _topic0_matches(log, expected):
        return None
    data = log.get("data")
    if data is None:
        return None
    if hasattr(data, "hex"):
        dh = data.hex()
    else:
        dh = str(data)
    return _decode_condition_resolution_data(dh)
