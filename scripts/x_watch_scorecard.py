# -*- coding: utf-8 -*-
"""X trader 账号统一持有期记分卡（2026-08-18 建）。

🔴 **为什么要这个**：日常台账那张表的「自提及%」是**自提及至今**，
   受持有期长短污染——7/05 的条目有六周、8/17 的只有一天，两者根本不能比。
   拿它排账号强弱、进而改降权规则，等于用「谁被提及得早」当因子。
   Vic 2026-08-18：「其他账号回溯周报做完全统计，我们再定」。

🎯 **口径**：对每条点名，取**提及日之后第 N 个交易日的收盘**（默认 N=5），
   相对 ref_price 算收益。样本不足 N 天的单列成「未成熟」，**不混进统计**——
   不足期的条目按现价算会系统性偏向最近几天的行情。

用法：
    python scripts/x_watch_scorecard.py              # D+5
    python scripts/x_watch_scorecard.py --days 10
    python scripts/x_watch_scorecard.py --json
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def load_entries():
    d = json.loads((ROOT / "data" / "x_watch.json").read_text(encoding="utf-8"))
    return d["entries"]


def forward_return(bars, mention_date, ref_price, days):
    """提及日之后第 days 个交易日的收盘 vs ref_price。

    提及日当天不算（当天的价已经反映在 ref_price 里——ref_price 的定义是
    「提及前最后一个收盘价」）。返回 (pct, 是否成熟)。
    """
    idx = None
    for i, b in enumerate(bars):
        if str(b.get("date", ""))[:10] > str(mention_date)[:10]:
            idx = i
            break
    if idx is None:
        return (None, False)
    tgt = idx + days - 1
    if tgt >= len(bars):
        return (((bars[-1]["c"] / ref_price - 1) * 100), False)   # 未成熟
    return (((bars[tgt]["c"] / ref_price - 1) * 100), True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    import fetch_market_data as F
    from longport.openapi import QuoteContext, Config
    ctx = QuoteContext(Config.from_apikey_env())

    entries = load_entries()
    tickers = sorted({e["ticker"] for e in entries})
    bars_by = {}
    for t in tickers:
        try:
            bars_by[t] = F.fetch_bars(ctx, t, 260) or []
        except Exception:
            bars_by[t] = []

    per = {}
    for e in entries:
        b = bars_by.get(e["ticker"]) or []
        if not b or not e.get("ref_price"):
            continue
        pct, mature = forward_return(b, e["date"], e["ref_price"], a.days)
        if pct is None:
            continue
        s = per.setdefault(e["handle"], {"mature": [], "young": []})
        s["mature" if mature else "young"].append((e["date"], e["ticker"], round(pct, 2)))

    out = []
    for h, s in per.items():
        m = [x[2] for x in s["mature"]]
        row = {"handle": h, "n_mature": len(m), "n_young": len(s["young"])}
        if m:
            row.update({"win_rate": round(sum(1 for x in m if x > 0) / len(m) * 100, 1),
                        "median": round(statistics.median(m), 2),
                        "mean": round(sum(m) / len(m), 2),
                        "best": max(m), "worst": min(m)})
        out.append(row)
    out.sort(key=lambda r: (-(r.get("n_mature") or 0)))

    if a.json:
        print(json.dumps({"days": a.days, "rows": out, "detail": per},
                         ensure_ascii=False, indent=1))
        return

    print("X trader 记分卡 · 统一持有期 D+%d（提及日后第 %d 个交易日收盘 vs 提及时参考价）"
          % (a.days, a.days))
    print("**未成熟条目（不足 %d 个交易日）单列，不进统计**\n" % a.days)
    print("%-20s %8s %8s %8s %9s %9s %9s %8s" % (
        "账号", "成熟n", "未成熟", "胜率", "中位数", "均值", "最好", "最差"))
    for r in out:
        if not r.get("n_mature"):
            print("%-20s %8d %8d   —（样本不足）" % (r["handle"], 0, r["n_young"]))
            continue
        print("%-20s %8d %8d %7.0f%% %+8.2f%% %+8.2f%% %+8.2f%% %+7.2f%%" % (
            r["handle"], r["n_mature"], r["n_young"], r["win_rate"],
            r["median"], r["mean"], r["best"], r["worst"]))


if __name__ == "__main__":
    main()
