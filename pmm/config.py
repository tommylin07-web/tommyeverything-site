from __future__ import annotations
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # --- capital & risk (USDC) ---
    total_capital: float = 100.0        # max USDC the bot may commit across all markets
    capital_per_market: float = 40.0    # max USDC resting per market (both sides combined)
    max_markets: int = 3
    max_inventory_usd: float = 30.0     # stop bidding a side once we hold this much notional of it
    daily_loss_limit: float = 5.0       # kill switch: cancel everything if MTM loss exceeds this
    # --- quoting ---
    quote_offset_frac: float = 0.5      # distance from midpoint as a fraction of the market's max spread
    requote_ticks: int = 2              # re-place orders when mid moves this many ticks
    loop_seconds: int = 30
    # --- market selection ---
    min_daily_rate: float = 5.0         # ignore markets with less than this USDC/day in rewards
    min_days_to_end: float = 3.0
    max_abs_day_change: float = 0.08    # skip markets whose price moved more than this in 24h
    exclude_sports: bool = True
    max_share: float = 0.5             # never assume we capture more than this share of a market's daily pool
    max_book_spread_frac: float = 3.0   # skip markets whose live spread is wider than this many max-spreads (mid is noise)
    mid_lo: float = 0.08
    mid_hi: float = 0.92
    # --- live credentials (env only; never written to disk) ---
    private_key: str | None = field(default=None, repr=False)
    wallet: str | None = None
    data_dir: str = "data"

    @classmethod
    def from_env(cls) -> "Config":
        c = cls()
        c.private_key = os.environ.get("POLY_PRIVATE_KEY")
        c.wallet = os.environ.get("POLY_WALLET") or os.environ.get("POLY_FUNDER")
        for k in ("total_capital", "capital_per_market", "max_inventory_usd", "daily_loss_limit", "quote_offset_frac", "min_daily_rate"):
            v = os.environ.get("PMM_" + k.upper())
            if v:
                setattr(c, k, float(v))
        for k in ("max_markets", "loop_seconds", "requote_ticks"):
            v = os.environ.get("PMM_" + k.upper())
            if v:
                setattr(c, k, int(v))
        return c
