"""Live executor on top of the official `polymarket-client` SDK.

Only used with `--live`; every call is guarded. Not exercised against a real account in CI.
"""
from __future__ import annotations
import os


class LiveExecutor:
    def __init__(self, private_key: str, wallet: str | None):
        from polymarket import SecureClient
        self.client = SecureClient.create(private_key=private_key, wallet=wallet)

    def usdc_balance(self) -> float:
        ba = self.client.get_balance_allowance(asset_type="COLLATERAL")
        return ba.balance / 1e6          # USDC has 6 decimals; SDK returns base units

    def approvals_ok(self) -> bool:
        return self.client.get_trading_approvals_state().is_fully_approved

    def place_bid(self, token_id: str, price: float, size: float) -> str | None:
        r = self.client.place_limit_order(token_id=token_id, price=price, size=size, side="BUY", post_only=True)
        if not getattr(r, "ok", False):
            print("order rejected:", r)
            return None
        return r.order_id

    def open_orders(self):
        return list(self.client.list_open_orders())

    def cancel_all(self):
        return self.client.cancel_all()

    def cancel_market(self, condition_id: str):
        return self.client.cancel_market_orders(market=condition_id)


def guard_live() -> None:
    if os.environ.get("PMM_I_UNDERSTAND_REAL_MONEY") != "1":
        raise SystemExit("refusing --live: set PMM_I_UNDERSTAND_REAL_MONEY=1 after reading README 风险 section")
    if not os.environ.get("POLY_PRIVATE_KEY"):
        raise SystemExit("POLY_PRIVATE_KEY not set")
