#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Weinstein 四阶段全量分布——自己算，不再依赖老师的 Google Sheet。

背景（2026-08-07）：老师维护的「S&P 500 LIVE MARKET BREADTH」tab(gid=90181001) 返回 HTTP 400，
COMBINED tab(gid=90181401) 能取但**表内时间戳停在 2026-07-31**。Vic 确认：「w stages 我老师是
停止维护了，我也不知道哪里拿」。

我们本来就有算法（fetch_market_data.weinstein_stage：30周均线 ≈150交易日 + 其10日斜率，
带 ±0.5% 死区防止来回翻档），缺的只是"算多少只"——以前只算 ~91 只 quick universe。
这个脚本把票池换成 reference/ETF_Holdings.csv（Vic 自己维护的 11 个 XL 板块全成分），
去掉非美股代码后约 700 只，覆盖度跟老师那份(2467只，S&P500+NDX100+R2K+Dow30)口径不同但
分布比例可比——**用 --asof 2026-07-31 跑一遍就能跟老师最后一份快照对照，验证算法没跑偏。**

用法：
    python scripts/scan_weinstein.py                    # 算到最新收盘
    python scripts/scan_weinstein.py --asof 2026-07-31  # 算到指定日（用于对标验证）
输出：屏幕分布表 + data/cache/weinstein_YYYYMMDD.json
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_market_data as F

STAGE_NAME = {1: "Stage 1 筑底", 2: "Stage 2 上升", 3: "Stage 3 派发", 4: "Stage 4 下降"}
# 老师最后一份快照（2026-07-31，2428只已分类）——留作对标基线
MENTOR_20260731 = {1: 21.7, 2: 36.8, 3: 25.9, 4: 15.6}


def universe():
    """ETF_Holdings 全成分，去掉非美股（外国代码带点/数字开头）与现金行。"""
    path = ROOT / "reference" / "ETF_Holdings.csv"
    out = set()
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        t = (r.get("Ticker") or "").strip().upper()
        if not t or t.startswith("-") or "." in t or t[0].isdigit():
            continue
        out.add(t)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="算到这一天为止（YYYY-MM-DD），用于跟历史快照对标")
    ap.add_argument("--limit", type=int, help="只算前N只（调试用）")
    # 2026-08-07 Vic：「每日看盘的确会出现这样的信号，但是不要进，我们也有5日信号在里面」
    # ——所以这个指标默认就出**序列不出单点**：一次拉完 bars 后对最近 N 个交易日各算一次截面，
    # 看的是 Stage 2/4 占比往哪个方向走，而不是今天是 45.5% 还是 44.8%。
    ap.add_argument("--series", type=int, default=10, help="同时算最近N个交易日的分布序列（默认10）")
    args = ap.parse_args()

    from longport.openapi import QuoteContext, Config
    ctx = QuoteContext(Config.from_apikey_env())

    tickers = universe()
    if args.limit:
        tickers = tickers[:args.limit]
    print("票池 %d 只（reference/ETF_Holdings.csv 去非美股）" % len(tickers))

    stages = Counter()
    by_stage = {1: [], 2: [], 3: [], 4: []}
    failed, unclassified = [], []
    data_date = None
    series = {}          # {日期: Counter()}——同一批 bars 算多个截面，不重复拉数据
    for i, t in enumerate(tickers, 1):
        if i % 100 == 0:
            print("  ... %d/%d" % (i, len(tickers)))
        try:
            bars = F.fetch_bars(ctx, t, 220)
        except Exception:
            failed.append(t)
            continue
        if not bars:           # fetch_bars 对无效代码返回 None（如货币基金 FGXXX）
            failed.append(t)
            continue
        if args.asof:
            bars = [b for b in bars if b["date"] <= args.asof]
        if len(bars) < 160:          # 150日均线 + 10日斜率，不够长的不判
            unclassified.append(t)
            continue
        m = F.analyze(bars)
        st = m.get("weinstein_stage")
        if st is None:
            unclassified.append(t)
            continue
        stages[st] += 1
        by_stage[st].append(t)
        data_date = data_date or bars[-1]["date"]
        # 序列：往回退 k 天各算一次（bars 已在手上，只是切片，几乎不额外耗时）
        for k in range(1, args.series):
            sub = bars[:-k]
            if len(sub) < 160:
                continue
            sk = F.analyze(sub).get("weinstein_stage")
            if sk:
                series.setdefault(sub[-1]["date"], Counter())[sk] += 1

    total = sum(stages.values())
    print("\n数据截至 %s ｜ 已分类 %d 只 ｜ 拉取失败 %d ｜ 样本不足 %d\n"
          % (data_date, total, len(failed), len(unclassified)))
    print("%-14s %-8s %-9s %s" % ("阶段", "只数", "占比", "老师7/31基线"))
    print("-" * 52)
    for s in (1, 2, 3, 4):
        pct = stages[s] / total * 100 if total else 0
        print("%-14s %-8d %-9s %.1f%%" % (STAGE_NAME[s], stages[s], "%.1f%%" % pct,
                                          MENTOR_20260731[s]))
    print("-" * 52)
    print("%-14s %-8d" % ("合计", total))

    # 序列（最新在下）——Vic 2026-08-07：日度单点不看，看往哪个方向走
    ser_rows = []
    if series:
        print("\n近 %d 个交易日分布序列（Stage2=上升 / Stage4=下降 是主线）：" % args.series)
        print("%-12s %-8s %-8s %-8s %-8s %s" % ("日期", "S1筑底", "S2上升", "S3派发", "S4下降", "S2-S4"))
        print("-" * 62)
        allser = dict(series)
        allser[data_date] = stages
        for dt in sorted(allser):
            cn = allser[dt]
            tot = sum(cn.values()) or 1
            p = {s: cn[s] / tot * 100 for s in (1, 2, 3, 4)}
            spread = p[2] - p[4]
            print("%-12s %-8s %-8s %-8s %-8s %+.1fpt" % (
                dt, "%.1f%%" % p[1], "%.1f%%" % p[2], "%.1f%%" % p[3], "%.1f%%" % p[4], spread))
            ser_rows.append({"date": dt, "n": tot,
                             **{"s%d_pct" % s: round(p[s], 1) for s in (1, 2, 3, 4)},
                             "s2_minus_s4": round(spread, 1)})
        first, last = ser_rows[0], ser_rows[-1]
        print("\n区间变化：Stage2 %.1f%% → %.1f%%（%+.1fpt）｜ Stage4 %.1f%% → %.1f%%（%+.1fpt）"
              % (first["s2_pct"], last["s2_pct"], last["s2_pct"] - first["s2_pct"],
                 first["s4_pct"], last["s4_pct"], last["s4_pct"] - first["s4_pct"]))

    out = {
        "series": ser_rows,
        "data_date": data_date,
        "asof": args.asof,
        "universe_size": len(tickers),
        "classified": total,
        "failed": failed,
        "unclassified_n": len(unclassified),
        "stages": {str(s): {"count": stages[s],
                            "share_pct": round(stages[s] / total * 100, 1) if total else 0}
                   for s in (1, 2, 3, 4)},
        "tickers_by_stage": {str(s): by_stage[s] for s in (1, 2, 3, 4)},
    }
    ds = (data_date or "").replace("-", "")
    p = ROOT / "data" / "cache" / ("weinstein_%s.json" % ds)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nwrote %s" % p)


if __name__ == "__main__":
    main()
