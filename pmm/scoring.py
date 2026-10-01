"""Polymarket liquidity-reward scoring (docs.polymarket.com/market-makers/liquidity-rewards).

S(v, s) = ((v - s) / v)^2 * b      v = max spread (price units), s = distance from midpoint
Q_one   = sum S * size over YES bids (+ NO asks, same thing on a unified book)
Q_two   = sum S * size over YES asks (+ NO bids)
Q_min   = max(min(Q1, Q2), max(Q1, Q2) / 3)   if 0.10 <= mid <= 0.90
        = min(Q1, Q2)                          otherwise (two-sided only)
Daily reward share = our Q_min / sum of everyone's Q_min, sampled once a minute.
"""
from __future__ import annotations
from .api import Book

SINGLE_SIDED_DIVISOR = 3.0


def order_score(v: float, s: float, b: float = 1.0) -> float:
    if v <= 0 or s < 0 or s > v:
        return 0.0
    return ((v - s) / v) ** 2 * b


def q_min(q1: float, q2: float, mid: float) -> float:
    if 0.10 <= mid <= 0.90:
        return max(min(q1, q2), max(q1, q2) / SINGLE_SIDED_DIVISOR)
    return min(q1, q2)


def book_q(book: Book, v: float, min_size: float, mid: float | None = None) -> tuple[float, float]:
    """(Q_one, Q_two) of everything currently resting in the YES book within max spread."""
    mid = mid if mid is not None else book.mid
    if mid is None:
        return 0.0, 0.0
    q1 = sum(order_score(v, mid - l.price) * l.size for l in book.bids if l.size >= min_size)
    q2 = sum(order_score(v, l.price - mid) * l.size for l in book.asks if l.size >= min_size)
    return q1, q2


def our_q(v: float, mid: float, bid_price: float, bid_size: float, ask_price: float, ask_size: float) -> float:
    """Q_min for one two-sided quote: a YES bid and a YES ask (a NO bid at 1-ask_price is the same thing)."""
    q1 = order_score(v, mid - bid_price) * bid_size
    q2 = order_score(v, ask_price - mid) * ask_size
    return q_min(q1, q2, mid)


def expected_daily_reward(rate: float, ours: float, others: float, max_share: float = 0.5) -> float:
    """Our share of the pool, capped: an empty band today will not stay empty once we quote in it."""
    if ours <= 0:
        return 0.0
    return rate * min(ours / (ours + others), max_share)
