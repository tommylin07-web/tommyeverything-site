import time
from pmm.api import Book, Level
from pmm.config import Config
from pmm.paper import PaperEngine, detect_fills
from pmm.quoting import Quote
from pmm.select import Candidate


def cand(mid=0.5):
    return Candidate("cid", "Q?", "YES", "NO", mid, 0.01, 0.04, 20, 100, 50, 10, 16, 40, 0.0, 30)


def book(bid, ask, size=100):
    return Book("YES", [Level(bid, size)], [Level(ask, size)], 0.01, 5)


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


def test_engine_ignores_trades_older_than_the_quote(tmp_path):
    cfg = Config(data_dir=str(tmp_path), loop_seconds=60)
    eng = PaperEngine(cfg, [cand()])
    old_tape = [dict(timestamp=50, price=0.40, side="SELL", asset="YES"), dict(timestamp=60, price=0.60, side="BUY", asset="YES")]
    eng.step(now=100, books={"YES": book(0.49, 0.51)}, trades_fn=lambda cid: old_tape)     # quote placed at t=100
    eng.step(now=160, books={"YES": book(0.49, 0.51)}, trades_fn=lambda cid: old_tape)
    assert eng.state.markets["cid"].fills == 0
    new_tape = old_tape + [dict(timestamp=150, price=0.47, side="SELL", asset="YES")]
    eng.step(now=220, books={"YES": book(0.49, 0.51)}, trades_fn=lambda cid: new_tape)
    assert eng.state.markets["cid"].fills == 1 and eng.state.markets["cid"].yes_inv > 0


def test_requote_needs_confirmation_and_ignores_dust(tmp_path):
    cfg = Config(data_dir=str(tmp_path), requote_confirm_loops=2)
    eng = PaperEngine(cfg, [cand()])
    ms = eng.state.markets["cid"]
    eng.step(now=1, books={"YES": book(0.49, 0.51)}, trades_fn=None)
    assert ms.quote_mid == 0.50
    # a dust order pulls the raw mid but not the adjusted one: nothing happens
    eng.step(now=2, books={"YES": Book("YES", [Level(0.49, 100)], [Level(0.50, 5), Level(0.51, 100)], 0.01, 5)}, trades_fn=None)
    assert ms.quote_mid == 0.50 and ms.pending_mid is None and ms.fills == 0
    # a real move (2 ticks, not through our prices) must persist two loops before we follow it
    eng.step(now=3, books={"YES": book(0.47, 0.49)}, trades_fn=None)
    assert ms.quote_mid == 0.50 and ms.pending_loops == 1 and ms.fills == 0
    eng.step(now=4, books={"YES": book(0.47, 0.49)}, trades_fn=None)
    assert abs(ms.quote_mid - 0.48) < 1e-9 and ms.pending_loops == 0


def test_quotes_pulled_when_book_blows_out(tmp_path):
    cfg = Config(data_dir=str(tmp_path), max_book_spread_frac=3.0)
    eng = PaperEngine(cfg, [cand()])
    ms = eng.state.markets["cid"]
    eng.step(now=1, books={"YES": book(0.49, 0.51)}, trades_fn=None)
    assert ms.quote
    eng.step(now=2, books={"YES": book(0.30, 0.70)}, trades_fn=None)     # 40c wide vs 4c band
    assert ms.quote is None
    eng.step(now=3, books={"YES": book(0.49, 0.51)}, trades_fn=None)
    assert ms.quote and ms.quote_mid == 0.50


def test_resume_restores_state(tmp_path):
    cfg = Config(data_dir=str(tmp_path), loop_seconds=60)
    eng = PaperEngine(cfg, [cand()])
    eng.step(now=1, books={"YES": book(0.49, 0.51)}, trades_fn=None)
    eng.step(now=2, books={"YES": book(0.46, 0.47)}, trades_fn=None)          # fill + reward accrued
    before = eng.state.markets["cid"]
    assert PaperEngine.resume(Config(data_dir=str(tmp_path / "nope"))) is None
    eng2 = PaperEngine.resume(cfg)
    after = eng2.state.markets["cid"]
    assert (after.yes_inv, after.cost, after.reward, after.fills, after.quote, after.quote_ts) == \
           (before.yes_inv, before.cost, before.reward, before.fills, before.quote, before.quote_ts)
    assert eng2.state.started == eng.state.started and eng2.halted is False
    eng2.step(now=3, books={"YES": book(0.46, 0.47)}, trades_fn=None)
    assert eng2.state.markets["cid"].reward > before.reward


def test_per_market_halt_keeps_other_markets_quoting(tmp_path):
    cfg = Config(data_dir=str(tmp_path), market_loss_limit=3.0, daily_loss_limit=100.0)
    other = Candidate("other", "O?", "OY", "ON", 0.5, 0.01, 0.04, 20, 100, 50, 10, 16, 40, 0.0, 30)
    eng = PaperEngine(cfg, [cand(), other])
    books = {"YES": book(0.49, 0.51), "OY": Book("OY", [Level(0.49, 100)], [Level(0.51, 100)], 0.01, 5)}
    eng.step(now=1, books=books, trades_fn=None)
    eng.step(now=2, books={"YES": book(0.46, 0.47), "OY": books["OY"]}, trades_fn=None)   # fill at 0.48
    eng.step(now=3, books={"YES": book(0.38, 0.39), "OY": books["OY"]}, trades_fn=None)   # now worth 0.385: loss > 3
    bad, good = eng.state.markets["cid"], eng.state.markets["other"]
    assert bad.halted and bad.quote is None
    assert not good.halted and good.quote and not eng.halted
    eng.step(now=4, books={"YES": book(0.49, 0.51), "OY": books["OY"]}, trades_fn=None)   # recovery does not re-arm
    assert bad.halted and bad.quote is None
