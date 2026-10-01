from __future__ import annotations
from dataclasses import dataclass
import math
from .config import Config


@dataclass
class Quote:
    yes_bid: float      # price we bid for YES
    no_bid: float       # price we bid for NO  (== selling YES at 1 - no_bid)
    size: float         # shares per side


def round_to_tick(p: float, tick: float, down: bool) -> float:
    n = p / tick
    n = math.floor(n + 1e-9) if down else math.ceil(n - 1e-9)
    return round(n * tick, 6)


def make_quote(mid: float, max_spread: float, tick: float, min_size: float, cfg: Config,
               yes_inv_usd: float = 0.0, no_inv_usd: float = 0.0) -> Quote | None:
    """Two bids, symmetric around mid, `quote_offset_frac` of the max spread away.

    Inventory skew: the side we already hold too much of is pushed one tick further out;
    beyond max_inventory_usd that side is dropped entirely (size 0 => caller skips it).
    """
    if mid is None or mid <= 0 or mid >= 1:
        return None
    d = max(tick, cfg.quote_offset_frac * max_spread)
    d = min(d, max_spread - tick)            # stay strictly inside the reward band
    yes_bid = round_to_tick(mid - d, tick, down=True)
    yes_ask = round_to_tick(mid + d, tick, down=False)
    if yes_bid <= 0 or yes_ask >= 1:
        return None
    no_bid = round(1 - yes_ask, 6)
    # size: half the per-market capital on each side, priced at the dearer side
    per_side_usd = cfg.capital_per_market / 2
    size = max(min_size, math.floor(per_side_usd / max(yes_bid, no_bid)))
    if size * max(yes_bid, no_bid) > per_side_usd * 1.5:
        return None                           # min size alone would blow the budget
    if yes_inv_usd >= cfg.max_inventory_usd:
        yes_bid = 0.0
    if no_inv_usd >= cfg.max_inventory_usd:
        no_bid = 0.0
    return Quote(yes_bid, no_bid, float(size))
