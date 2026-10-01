"""Paper-trading engine: our orders never touch the exchange.

Fill model (conservative): a resting bid is considered filled when the live book or the
public trade tape trades *through* its price. Reward accrual: every loop we recompute our
share of Q against the real book and accrue rate * share * (loop_seconds / 86400).
"""
from __future__ import annotations
import csv
import json
import os
import time
from dataclasses import dataclass, field, asdict

from . import api
from .config import Config
from .quoting import Quote, make_quote
from .scoring import book_q, our_q, q_min, expected_daily_reward
from .select import Candidate


@dataclass
class MarketState:
    cand: dict
    quote: dict | None = None
    quote_mid: float | None = None
    yes_inv: float = 0.0
    no_inv: float = 0.0
    cost: float = 0.0              # USDC paid for inventory
    reward: float = 0.0            # accrued estimated rewards
    fills: int = 0
    last_trade_ts: int = 0
    quote_ts: int = 0              # trades before this instant can never have filled the current quote
    pending_mid: float | None = None   # candidate new mid waiting for confirmation
    pending_loops: int = 0


@dataclass
class PaperState:
    started: float = field(default_factory=time.time)
    markets: dict[str, MarketState] = field(default_factory=dict)


def detect_fills(book: api.Book, quote: Quote, trades: list[dict], yes_token: str, since_ts: int) -> tuple[bool, bool]:
    """Returns (yes_filled, no_filled)."""
    yes_f = no_f = False
    if quote.yes_bid and book.best_ask is not None and book.best_ask <= quote.yes_bid:
        yes_f = True
    if quote.no_bid and book.best_bid is not None and book.best_bid >= 1 - quote.no_bid:
        no_f = True
    for t in trades:
        if int(t.get("timestamp", 0)) <= since_ts:
            continue
        p, side, asset = float(t["price"]), t.get("side"), t.get("asset")
        yes_price = p if asset == yes_token else 1 - p          # normalise to YES price
        yes_side = side if asset == yes_token else ("BUY" if side == "SELL" else "SELL")
        if quote.yes_bid and yes_side == "SELL" and yes_price <= quote.yes_bid:
            yes_f = True
        if quote.no_bid and yes_side == "BUY" and yes_price >= 1 - quote.no_bid:
            no_f = True
    return yes_f, no_f


def mtm(ms: MarketState, mid: float) -> float:
    return ms.yes_inv * mid + ms.no_inv * (1 - mid) - ms.cost


class PaperEngine:
    def __init__(self, cfg: Config, candidates: list[Candidate]):
        self.cfg = cfg
        os.makedirs(cfg.data_dir, exist_ok=True)
        self.state_path = os.path.join(cfg.data_dir, "paper_state.json")
        self.log_path = os.path.join(cfg.data_dir, "paper_log.csv")
        self.state = PaperState()
        for c in candidates[: cfg.max_markets]:
            self.state.markets[c.condition_id] = MarketState(cand=asdict(c))
        self.halted = False

    @classmethod
    def resume(cls, cfg: Config) -> "PaperEngine | None":
        """Continue a previous run from data/paper_state.json (inventory, rewards, quotes and tape watermarks)."""
        path = os.path.join(cfg.data_dir, "paper_state.json")
        if not os.path.exists(path):
            return None
        raw = json.load(open(path))
        eng = cls(cfg, [])
        eng.state.started = raw["started"]
        eng.halted = raw["halted"]
        eng.state.markets = {k: MarketState(**v) for k, v in raw["markets"].items()}
        return eng

    # ---- one iteration -------------------------------------------------
    def step(self, now: float | None = None, books: dict[str, api.Book] | None = None, trades_fn=api.recent_trades) -> list[dict]:
        now = now or time.time()
        cfg = self.cfg
        if books is None:
            books = api.get_books([ms.cand["yes"] for ms in self.state.markets.values()])
        rows = []
        for cid, ms in self.state.markets.items():
            c = ms.cand
            b = books.get(c["yes"])
            v, min_size = c["max_spread"], c["min_size"]
            mid, spread = b.adjusted(min_size) if b else (None, None)
            if mid is None:
                continue
            # 1. fills against the quote that was resting during the last interval
            if ms.quote and not self.halted:
                q = Quote(**ms.quote)
                trades = trades_fn(cid) if trades_fn else []
                yes_f, no_f = detect_fills(b, q, trades, c["yes"], max(ms.last_trade_ts, ms.quote_ts))
                if trades:
                    ms.last_trade_ts = max(ms.last_trade_ts, max(int(t.get("timestamp", 0)) for t in trades))
                if yes_f:
                    ms.yes_inv += q.size; ms.cost += q.size * q.yes_bid; ms.fills += 1; ms.quote = None
                if no_f:
                    ms.no_inv += q.size; ms.cost += q.size * q.no_bid; ms.fills += 1; ms.quote = None
            # 2. reward accrual for the interval the quote was resting
            if ms.quote and not self.halted:
                q = Quote(**ms.quote)
                q1, q2 = book_q(b, v, min_size)
                ours = our_q(v, mid, q.yes_bid, q.size if q.yes_bid else 0, 1 - q.no_bid if q.no_bid else 1, q.size if q.no_bid else 0)
                ms.reward += expected_daily_reward(c["daily_rate"], ours, q_min(q1, q2, mid), cfg.max_share) * cfg.loop_seconds / 86400
            # 3. (re)quote, with hysteresis: a moved mid must persist `requote_confirm_loops` loops
            if not self.halted:
                if spread > cfg.max_book_spread_frac * v:
                    ms.quote = None                      # book blew out: pull quotes rather than chase noise
                    ms.pending_mid, ms.pending_loops = None, 0
                else:
                    moved = ms.quote is not None and abs(mid - (ms.quote_mid or mid)) >= cfg.requote_ticks * b.tick
                    if moved:
                        if ms.pending_mid is not None and abs(mid - ms.pending_mid) < cfg.requote_ticks * b.tick:
                            ms.pending_loops += 1
                        else:
                            ms.pending_mid, ms.pending_loops = mid, 1
                    else:
                        ms.pending_mid, ms.pending_loops = None, 0
                    if ms.quote is None or (moved and ms.pending_loops >= cfg.requote_confirm_loops):
                        nq = make_quote(mid, v, b.tick, min_size, cfg, ms.yes_inv * mid, ms.no_inv * (1 - mid))
                        ms.quote = asdict(nq) if nq else None
                        ms.quote_mid = mid
                        ms.quote_ts = int(now)
                        ms.pending_mid, ms.pending_loops = None, 0
            rows.append(dict(ts=int(now), market=c["question"][:50], mid=round(mid, 4),
                             yes_bid=ms.quote and ms.quote["yes_bid"], no_bid=ms.quote and ms.quote["no_bid"],
                             size=ms.quote and ms.quote["size"], yes_inv=ms.yes_inv, no_inv=ms.no_inv,
                             fills=ms.fills, reward=round(ms.reward, 4), mtm=round(mtm(ms, mid), 4)))
        total_mtm = sum(r["mtm"] for r in rows)
        if total_mtm < -cfg.daily_loss_limit:
            self.halted = True
        self._persist(rows)
        return rows

    def _persist(self, rows):
        with open(self.state_path, "w") as f:
            json.dump({"started": self.state.started, "halted": self.halted,
                       "markets": {k: asdict(v) for k, v in self.state.markets.items()}}, f, indent=1)
        new = not os.path.exists(self.log_path)
        with open(self.log_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["ts"])
            if new:
                w.writeheader()
            w.writerows(rows)

    def summary(self) -> dict:
        hrs = (time.time() - self.state.started) / 3600
        reward = sum(m.reward for m in self.state.markets.values())
        return dict(hours=round(hrs, 2), reward_est=round(reward, 4), fills=sum(m.fills for m in self.state.markets.values()),
                    inventory_cost=round(sum(m.cost for m in self.state.markets.values()), 2), halted=self.halted,
                    reward_per_day_est=round(reward / hrs * 24, 4) if hrs > 0 else 0.0)
