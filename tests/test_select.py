import json
from pmm import select, api
from pmm.api import Book, Level
from pmm.config import Config


def test_rank_filters_and_orders(monkeypatch):
    rewards = [dict(condition_id="A", total_daily_rate=50, rewards_max_spread=4.0, rewards_min_size=20),
               dict(condition_id="B", total_daily_rate=50, rewards_max_spread=4.0, rewards_min_size=20),
               dict(condition_id="S", total_daily_rate=500, rewards_max_spread=4.0, rewards_min_size=20),
               dict(condition_id="L", total_daily_rate=1, rewards_max_spread=4.0, rewards_min_size=20)]
    base = dict(active=True, closed=False, acceptingOrders=True, enableOrderBook=True, endDate="2099-01-01T00:00:00Z", oneDayPriceChange=0.01)
    markets = [dict(base, conditionId="A", question="a", clobTokenIds=json.dumps(["Ay", "An"])),
               dict(base, conditionId="B", question="b", clobTokenIds=json.dumps(["By", "Bn"])),
               dict(base, conditionId="S", question="sport", sportsMarketType="moneyline", clobTokenIds=json.dumps(["Sy", "Sn"]))]
    books = {"Ay": Book("Ay", [Level(0.49, 10000)], [Level(0.51, 10000)], 0.01, 5),     # crowded
             "By": Book("By", [Level(0.49, 50)], [Level(0.51, 50)], 0.01, 5)}            # thin
    monkeypatch.setattr(api, "current_rewards", lambda: rewards)
    monkeypatch.setattr(api, "gamma_markets", lambda ids: [m for m in markets if m["conditionId"] in ids])
    monkeypatch.setattr(api, "get_books", lambda ids: {k: v for k, v in books.items() if k in ids})
    out = select.rank(Config(min_daily_rate=5))
    assert [c.condition_id for c in out] == ["B", "A"]          # sports excluded, low-rate excluded, thin book first
    assert out[0].exp_reward > out[1].exp_reward


def test_rank_skips_books_wider_than_band(monkeypatch):
    rewards = [dict(condition_id="W", total_daily_rate=50, rewards_max_spread=4.0, rewards_min_size=20)]
    m = dict(active=True, closed=False, acceptingOrders=True, enableOrderBook=True, endDate="2099-01-01T00:00:00Z",
             conditionId="W", question="w", clobTokenIds=json.dumps(["Wy", "Wn"]))
    monkeypatch.setattr(api, "current_rewards", lambda: rewards)
    monkeypatch.setattr(api, "gamma_markets", lambda ids: [m])
    monkeypatch.setattr(api, "get_books", lambda ids: {"Wy": Book("Wy", [Level(0.30, 50)], [Level(0.70, 50)], 0.01, 5)})
    assert select.rank(Config(min_daily_rate=5)) == []
