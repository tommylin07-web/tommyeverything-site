"""Thin read-only wrappers over Polymarket public endpoints (no auth)."""
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"

_session = requests.Session()
if os.environ.get("REQUESTS_CA_BUNDLE") is None and os.path.exists("/root/.ccr/ca-bundle.crt"):
    _session.verify = "/root/.ccr/ca-bundle.crt"


def _get(url, params=None, retries=3):
    for i in range(retries):
        try:
            r = _session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _post(url, body, retries=3):
    for i in range(retries):
        try:
            r = _session.post(url, json=body, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))


@dataclass
class Level:
    price: float
    size: float


@dataclass
class Book:
    token_id: str
    bids: list[Level]   # sorted best (highest) first
    asks: list[Level]   # sorted best (lowest) first
    tick: float
    min_size: float

    @property
    def best_bid(self):
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self):
        return self.asks[0].price if self.asks else None

    @property
    def mid(self):
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    def adjusted(self, min_size: float) -> tuple[float | None, float | None]:
        """(mid, spread) ignoring levels below `min_size`: Polymarket's size-cutoff-adjusted midpoint.
        A 5-share order should not be allowed to move where we quote."""
        bids = [l.price for l in self.bids if l.size >= min_size]
        asks = [l.price for l in self.asks if l.size >= min_size]
        if not bids or not asks:
            return None, None
        return (bids[0] + asks[0]) / 2, asks[0] - bids[0]


def parse_book(raw: dict) -> Book:
    bids = sorted((Level(float(x["price"]), float(x["size"])) for x in raw.get("bids", [])), key=lambda l: -l.price)
    asks = sorted((Level(float(x["price"]), float(x["size"])) for x in raw.get("asks", [])), key=lambda l: l.price)
    return Book(raw["asset_id"], bids, asks, float(raw.get("tick_size") or 0.01), float(raw.get("min_order_size") or 5))


def get_books(token_ids: list[str]) -> dict[str, Book]:
    out = {}
    for i in range(0, len(token_ids), 100):
        for raw in _post(f"{CLOB}/books", [{"token_id": t} for t in token_ids[i:i + 100]]):
            out[raw["asset_id"]] = parse_book(raw)
    return out


def get_book(token_id: str) -> Book:
    return parse_book(_get(f"{CLOB}/book", {"token_id": token_id}))


def current_rewards() -> list[dict]:
    """All markets currently paying liquidity rewards (paginated)."""
    out, cursor = [], None
    while True:
        params = {"limit": 500}
        if cursor:
            params["next_cursor"] = cursor
        page = _get(f"{CLOB}/rewards/markets/current", params)
        out += page.get("data", [])
        cursor = page.get("next_cursor")
        if not cursor or cursor == "LTE=" or not page.get("data"):
            break
    return out


def gamma_markets(condition_ids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(condition_ids), 20):
        out += _get(f"{GAMMA}/markets", [("condition_ids", c) for c in condition_ids[i:i + 20]] + [("limit", 100)])
    return out


def recent_trades(condition_id: str, limit: int = 50) -> list[dict]:
    return _get(f"{DATA}/trades", {"market": condition_id, "limit": limit})


def token_ids(market: dict) -> tuple[str, str]:
    yes, no = json.loads(market["clobTokenIds"])
    return yes, no
