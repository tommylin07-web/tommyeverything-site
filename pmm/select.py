"""Rank reward-paying markets by expected reward per USDC committed."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

from . import api
from .config import Config
from .quoting import make_quote
from .scoring import book_q, our_q, q_min, expected_daily_reward


@dataclass
class Candidate:
    condition_id: str
    question: str
    yes: str
    no: str
    mid: float
    tick: float
    max_spread: float       # price units (e.g. 0.045)
    min_size: float
    daily_rate: float
    others_q: float
    ours_q: float
    exp_reward: float       # USDC/day if the book stayed as it is
    capital: float          # USDC resting in our two bids
    day_change: float
    days_to_end: float
    jump: float = 0.0       # largest hourly move in the last week

    @property
    def yield_per_day(self) -> float:
        return self.exp_reward / self.capital if self.capital else 0.0


def _days_to_end(m: dict) -> float:
    try:
        end = datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
    except Exception:
        return 0.0
    return (end - datetime.now(timezone.utc)).total_seconds() / 86400


def passes_filters(m: dict, cfg: Config) -> bool:
    if m.get("closed") or not m.get("active") or not m.get("acceptingOrders") or not m.get("enableOrderBook"):
        return False
    if cfg.exclude_sports and m.get("sportsMarketType"):
        return False
    if _days_to_end(m) < cfg.min_days_to_end:
        return False
    if abs(float(m.get("oneDayPriceChange") or 0)) > cfg.max_abs_day_change:
        return False
    return True


def rank(cfg: Config, top_n_by_rate: int = 120) -> list[Candidate]:
    rewards = [r for r in api.current_rewards() if float(r["total_daily_rate"]) >= cfg.min_daily_rate and float(r["rewards_max_spread"]) > 0]
    rewards.sort(key=lambda r: -float(r["total_daily_rate"]))
    rewards = rewards[:top_n_by_rate]
    rw = {r["condition_id"]: r for r in rewards}
    markets = [m for m in api.gamma_markets(list(rw)) if passes_filters(m, cfg) and m["conditionId"] not in cfg.exclude_ids]
    books = api.get_books([api.token_ids(m)[0] for m in markets])
    out = []
    for m in markets:
        yes, no = api.token_ids(m)
        b = books.get(yes)
        r = rw[m["conditionId"]]
        v = float(r["rewards_max_spread"]) / 100
        min_size = max(float(r["rewards_min_size"]), b.min_size) if b else 0
        mid, spread = b.adjusted(min_size) if b else (None, None)
        if mid is None or not (cfg.mid_lo <= mid <= cfg.mid_hi):
            continue
        if spread > cfg.max_book_spread_frac * v:
            continue
        q = make_quote(mid, v, b.tick, min_size, cfg)
        if not q or not q.yes_bid or not q.no_bid:
            continue
        hist = api.price_history(yes)
        jump = api.max_jump(hist)
        if len(hist) < cfg.min_history_points or jump > cfg.max_hourly_jump:
            continue
        q1, q2 = book_q(b, v, min_size, mid)
        others = q_min(q1, q2, mid)
        ours = our_q(v, mid, q.yes_bid, q.size, 1 - q.no_bid, q.size)
        rate = float(r["total_daily_rate"])
        out.append(Candidate(m["conditionId"], m["question"], yes, no, mid, b.tick, v, min_size, rate,
                             others, ours, expected_daily_reward(rate, ours, others, cfg.max_share),
                             q.size * (q.yes_bid + q.no_bid), float(m.get("oneDayPriceChange") or 0), _days_to_end(m), jump))
    out.sort(key=lambda c: -c.yield_per_day)
    return out
