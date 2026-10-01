"""Summarise a paper run: python -m pmm.report [data/paper_log.csv]"""
from __future__ import annotations
import csv
import sys
from collections import defaultdict


def main(path="data/paper_log.csv"):
    rows = list(csv.DictReader(open(path)))
    if not rows:
        print("empty"); return
    by_ts = defaultdict(list)
    for r in rows:
        by_ts[int(r["ts"])].append(r)
    ts = sorted(by_ts)
    hours = (ts[-1] - ts[0]) / 3600
    series = [(t, sum(float(r["reward"]) for r in by_ts[t]), sum(float(r["mtm"]) for r in by_ts[t])) for t in ts]
    peak, dd = -1e9, 0.0
    for _, rw, m in series:
        pnl = rw + m
        peak = max(peak, pnl); dd = min(dd, pnl - peak)
    last = by_ts[ts[-1]]
    reward = sum(float(r["reward"]) for r in last); mtm = sum(float(r["mtm"]) for r in last)
    print(f"span {hours:.2f}h  samples {len(ts)}  reward_est {reward:.4f} (~{reward / hours * 24 if hours else 0:.2f}/day)  "
          f"inventory_mtm {mtm:+.3f}  net {reward + mtm:+.3f}  max_drawdown {dd:+.3f}")
    print(f"{'market':52} {'fills':>5} {'yes':>6} {'no':>6} {'reward':>7} {'mtm':>7}  quoted%")
    for m in sorted({r["market"] for r in rows}):
        mr = [r for r in rows if r["market"] == m]
        l = mr[-1]
        quoted = sum(1 for r in mr if r["yes_bid"] not in ("", "None")) / len(mr) * 100
        print(f"{m[:52]:52} {l['fills']:>5} {float(l['yes_inv']):6.0f} {float(l['no_inv']):6.0f} {float(l['reward']):7.3f} {float(l['mtm']):+7.3f}  {quoted:5.0f}%")


if __name__ == "__main__":
    main(*sys.argv[1:])
