from pmm.config import Config
from pmm.quoting import make_quote, round_to_tick


def test_round_to_tick():
    assert round_to_tick(0.4749, 0.01, down=True) == 0.47
    assert round_to_tick(0.4701, 0.01, down=False) == 0.48


def test_quote_geometry():
    cfg = Config(capital_per_market=40, quote_offset_frac=0.5)
    q = make_quote(0.50, 0.04, 0.01, 20, cfg)
    assert q.yes_bid == 0.48 and q.no_bid == 0.48           # symmetric 2c inside a 4c band
    assert q.size == 41                                      # floor(20 / 0.48)
    assert q.size * q.yes_bid <= 20 * 1.5


def test_quote_respects_inventory_cap_and_budget():
    cfg = Config(capital_per_market=40, max_inventory_usd=30)
    q = make_quote(0.50, 0.04, 0.01, 20, cfg, yes_inv_usd=31)
    assert q.yes_bid == 0.0 and q.no_bid > 0
    assert make_quote(0.50, 0.04, 0.01, 500, cfg) is None   # min size would exceed the budget
    assert make_quote(None, 0.04, 0.01, 20, cfg) is None
