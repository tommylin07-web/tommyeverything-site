import time
from pmm.api import Book, Level
from pmm.config import Config
from pmm.paper import PaperEngine, detect_fills
from pmm.quoting import Quote
from pmm.select import Candidate


def cand(mid=0.5):
    return Candidate("cid", "Q?", "YES", "NO", mid, 0.01, 0.04, 20, 100, 50, 10, 16, 40, 0.0, 30)


def book(bid, ask):
    return Book("YES", [Level(bid, 100)], [Level(ask, 100)], 0.01, 5)


def test_detect_fills_from_book_cross():
    q = Quote(0.48, 0.48, 40)
    assert detect_fills(book(0.49, 0.51), q, [], "YES", 0) == (False, False)
    assert detect_fills(book(0.46, 0.47), q, [], "YES", 0) == (True, False)    # asks traded down through our bid
    assert detect_fills(book(0.53, 0.54), q, [], "YES", 0) == (False, True)    # bids traded up through our NO bid (YES ask 0.52)


def test_detect_fills_from_tape_including_no_asset():
    q = Quote(0.48, 0.48, 40)
    tape = [dict(timestamp=10, price=0.47, side="SELL", asset="YES")]
    assert detect_fills(book(0.49, 0.51), q, tape, "YES", 0) == (True, False)
    assert detect_fills(book(0.49, 0.51), q, tape, "YES", 10) == (False, False)   # already seen
    tape = [dict(timestamp=11, price=0.47, side="SELL", asset="NO")]              # selling NO at 0.47 == buying YES at 0.53
    assert detect_fills(book(0.49, 0.51), q, tape, "YES", 0) == (False, True)


def test_engine_quotes_accrues_and_fills(tmp_path):
    cfg = Config(data_dir=str(tmp_path), loop_seconds=60, capital_per_market=40)
    eng = PaperEngine(cfg, [cand()])
    rows = eng.step(now=1, books={"YES": book(0.49, 0.51)}, trades_fn=None)
    ms = eng.state.markets["cid"]
    assert ms.quote and ms.quote["yes_bid"] == 0.48 and rows[0]["reward"] == 0
    eng.step(now=2, books={"YES": book(0.49, 0.51)}, trades_fn=None)
    assert ms.reward > 0                                                     # one minute of share accrued
    eng.step(now=3, books={"YES": book(0.46, 0.47)}, trades_fn=None)          # market crashes through our bid
    assert ms.fills == 1 and ms.yes_inv > 0 and ms.cost == ms.yes_inv * 0.48
    assert ms.quote and abs(ms.quote_mid - 0.465) < 1e-9                    # requoted around the new mid
    assert (tmp_path / "paper_log.csv").exists() and (tmp_path / "paper_state.json").exists()


def test_kill_switch(tmp_path):
    cfg = Config(data_dir=str(tmp_path), daily_loss_limit=1.0)
    eng = PaperEngine(cfg, [cand()])
    eng.step(now=1, books={"YES": book(0.49, 0.51)}, trades_fn=None)
    eng.step(now=2, books={"YES": book(0.40, 0.41)}, trades_fn=None)          # filled at 0.48, now worth 0.405
    eng.step(now=3, books={"YES": book(0.40, 0.41)}, trades_fn=None)
    assert eng.halted
