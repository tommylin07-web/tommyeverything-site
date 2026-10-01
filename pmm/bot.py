from __future__ import annotations
import argparse
import json
import signal
import sys
import time

from .config import Config
from .select import rank


def cmd_scan(cfg: Config, n: int):
    cands = rank(cfg)
    print(f"{'yield/d':>8} {'$/day':>7} {'cap$':>6} {'rate':>6} {'mid':>6} {'oursQ':>7} {'othQ':>8} {'Δ24h':>6} {'days':>5}  question")
    for c in cands[:n]:
        print(f"{c.yield_per_day*100:7.2f}% {c.exp_reward:7.2f} {c.capital:6.1f} {c.daily_rate:6.0f} {c.mid:6.3f} {c.ours_q:7.2f} {c.others_q:8.1f} {c.day_change:+6.2f} {c.days_to_end:5.0f}  {c.question[:60]}")
    return cands


def cmd_paper(cfg: Config, hours: float, resume: bool = False):
    from .paper import PaperEngine
    eng = PaperEngine.resume(cfg) if resume else None
    if eng:
        print(f"resumed: {len(eng.state.markets)} markets, {eng.summary()}")
    else:
        cands = cmd_scan(cfg, cfg.max_markets)
        if not cands:
            print("no candidates"); return
        eng = PaperEngine(cfg, cands)
    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))
    deadline = time.time() + hours * 3600
    while time.time() < deadline and not stop["flag"]:
        t0 = time.time()
        try:
            rows = eng.step()
            s = eng.summary()
            print(f"[{time.strftime('%H:%M:%S')}] reward_est={s['reward_est']:.4f} (~{s['reward_per_day_est']:.2f}/day) fills={s['fills']} "
                  f"mtm={sum(r['mtm'] for r in rows):+.3f} halted={s['halted']}", flush=True)
        except Exception as e:  # network hiccup: log and keep going
            print("step error:", repr(e), flush=True)
        time.sleep(max(1, cfg.loop_seconds - (time.time() - t0)))
    print(json.dumps(eng.summary(), indent=1))


def cmd_live(cfg: Config, hours: float):
    from .live import LiveExecutor, guard_live
    from .quoting import make_quote
    from . import api
    guard_live()
    ex = LiveExecutor(cfg.private_key, cfg.wallet)
    bal = ex.usdc_balance()
    print(f"wallet={cfg.wallet} usdc={bal:.2f} approvals_ok={ex.approvals_ok()}")
    if bal < cfg.total_capital:
        cfg.total_capital = bal
    cands = cmd_scan(cfg, cfg.max_markets)
    live = {c.condition_id: c for c in cands[: cfg.max_markets]}
    quoted: dict[str, tuple[float, list[str]]] = {}
    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))
    deadline = time.time() + hours * 3600
    try:
        while time.time() < deadline and not stop["flag"]:
            books = api.get_books([c.yes for c in live.values()])
            for cid, c in live.items():
                b = books.get(c.yes)
                mid, spread = b.adjusted(c.min_size) if b else (None, None)
                if mid is None:
                    continue
                prev_mid = quoted.get(cid, (None, []))[0]
                if prev_mid is not None and abs(mid - prev_mid) < cfg.requote_ticks * b.tick:
                    continue
                ex.cancel_market(cid)
                q = None if spread > cfg.max_book_spread_frac * c.max_spread else make_quote(mid, c.max_spread, b.tick, c.min_size, cfg)
                ids = []
                if q:
                    if q.yes_bid:
                        ids.append(ex.place_bid(c.yes, q.yes_bid, q.size))
                    if q.no_bid:
                        ids.append(ex.place_bid(c.no, q.no_bid, q.size))
                quoted[cid] = (mid, ids)
                print(f"[{time.strftime('%H:%M:%S')}] {c.question[:40]} mid={mid:.3f} quoted={q}", flush=True)
            time.sleep(cfg.loop_seconds)
    finally:
        print("cancelling all resting orders:", ex.cancel_all())


def main(argv=None):
    p = argparse.ArgumentParser(prog="pmm")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("-n", type=int, default=15)
    pp = sub.add_parser("paper"); pp.add_argument("--hours", type=float, default=1.0); pp.add_argument("--resume", action="store_true")
    lv = sub.add_parser("live"); lv.add_argument("--hours", type=float, default=1.0)
    a = p.parse_args(argv)
    cfg = Config.from_env()
    if a.cmd == "scan":
        cmd_scan(cfg, a.n)
    elif a.cmd == "paper":
        cmd_paper(cfg, a.hours, a.resume)
    else:
        cmd_live(cfg, a.hours)


if __name__ == "__main__":
    main()
