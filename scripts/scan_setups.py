#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方法2 · 强势板块成分股Setup扫描（2026-07-12建）。

票池两层：
  1. --sectors XLV,XLY  →  reference/ETF_Holdings.csv 里对应板块的全部成分股
     （Vic自己整理的11个XL板块503只成分清单，2026-07-12提供："目前的范围就用这些"）
  2. LongBridge watchlist全量US标的（约232只）——兜底票池，覆盖非XL板块（IHI/XBI/CIBR等无清单的主题）

用法： python scripts/scan_setups.py [--sectors XLV,XLY]
输出： data/cache/setups_YYYYMMDD.json + 终端摘要（带板块归属标注）
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_market_data import analyze  # 复用同一套指标口径

from longport.openapi import QuoteContext, Config, Period, AdjustType

# 🔴 K线复权口径统一走 fetch_market_data.BARS_ADJUST（2026-08-19 定）——
#    这里原本写死 NoAdjust，窗口跨过拆股就整段作废（CRWD 距50MA 报 -42% 真值 +11%）。
import report_helpers as _H  # noqa: E402
_ADJUST = _H.bars_adjust()


def get_watchlist_symbols(ctx):
    """LongBridge自选列表全量US标的（去重）。"""
    symbols = []
    for group in ctx.watchlist():
        for s in group.securities:
            if s.symbol.endswith(".US"):
                symbols.append(s.symbol)
    return sorted(set(symbols))


def load_etf_holdings():
    """Vic整理的XL板块成分清单：{ticker: [所属ETF,...]}，reference/ETF_Holdings.csv。"""
    import csv
    path = ROOT / "reference" / "ETF_Holdings.csv"
    membership = {}
    if not path.exists():
        return membership
    for row in csv.DictReader(open(path, encoding="utf-8-sig")):
        tk = row["Ticker"].strip()
        membership.setdefault(tk, []).append(row["ETF"].strip())
    return membership


def classify(m):
    """按CONTEXT.md「选股规则」的机器初筛参数打setup标签。返回[(setup, 说明)]。

    🔴 **2026-08-20 Vic 把 A/B/C/D/E 全部换成形态名**（原话：「abcde那些都好删除了」）：
        A → pullback（缩量回踩 9EMA）
        D → pullback（放量突破后缩量回踩）—— 同为回踩，说明文字里仍区分
        B → tight（高位收紧）
        C → spring（浅插针快速收回，Wyckoff spring；样本天然少，8/19 全场只有 2 个）
        E → shakeout+burst（深度洗盘 + 放量夺回）
        Ew → pullback（洗盘已收回但爆发 bar 未出现 —— 2026-08-20 Vic：「这个就是 Pullback」，
             做法跟回踩买点一样都是等一根 bar，动作相同就不该占两个标签名）
        W → 2 wick（双底/三重底，同一位置两次插针）
    ⚠️ **spring 和 shakeout+burst 不是同一个东西，不许合并**（2026-08-20 Vic 问过）：
       支撑窗口 15 根 vs 40 根、盘中破 vs 收盘破、3 根内收回 vs 待 ≥2 根、
       深度 ≤5% vs ≤20%，而且 **shakeout+burst 强制要求爆发 bar，spring 不要求**。
       合并 = 把两个不同的入场时点混成一个。
    """
    tags = []
    if m["rsi14"] is None or m.get("ma20") is None:
        return tags
    up_bg = (m.get("dist_ma50_pct") or -99) > 0 and m["rsi14"] >= 45  # 强势背景（人眼过滤的机器近似）
    # Setup B：tight consolidation（高位收紧，不是低位阴跌）
    if m.get("tight_5d") and m["rsi14"] >= 50 and (m.get("dist_ma20_pct") or -99) > 0 and m.get("ma20_slope_up"):
        tags.append(("tight", f"5日 {m['range5_pct']}%/{m['range5_atr']}ATR · RSI {m['rsi14']}"))
    # Setup A：缩量回踩9EMA（上升趋势中贴近9EMA）
    d9 = m.get("dist_ema9_pct")
    if up_bg and d9 is not None and -2.5 <= d9 <= 1.5 and m.get("ma20_slope_up") and (m.get("vol_ratio") or 9) < 1.0:
        tags.append(("pullback", f"距9EMA {d9}% · 量 {m.get('vol_ratio')}×"))
    # Setup C：undercut and rally（强势背景里的假跌破收回）
    if m.get("undercut_rally") and m["rsi14"] >= 45:
        u = m["undercut_rally"]
        tags.append(("spring", f"支撑 {u['support']} · 假破 {u['undercut_depth_pct']}%"))
    # Setup D：放量突破→缩量回踩
    if m.get("breakout_pullback"):
        b = m["breakout_pullback"]
        tags.append(("pullback", f"突破位 {b['pivot']}（{b['breakout_date']} 量{b['breakout_vol_ratio']}×）"))
    # Setup E：shakeout + momentum burst（深度洗盘后动量爆发，2026-07-15 Vic老师PLTR案例）
    if m.get("shakeout_burst"):
        s = m["shakeout_burst"]
        if s["burst"]:
            bu = s["burst"]
            tags.append(("shakeout+burst", f"收回 {s['support']}（深{s['depth_pct']}%/{s['days_below']}天）"
                              f" · burst {bu['date']} +{bu['gain_pct']}% 量{bu['vol_ratio']}×"))
        elif m["rsi14"] >= 40:
            tags.append(("pullback", f"收回 {s['support']}（深{s['depth_pct']}%）· burst 未确认"))
    # 加分结构：二次/三次探底未破前低
    if m.get("double_bottom"):
        db = m["double_bottom"]
        kind = "三重底" if db.get("triple") else "双底"
        tags.append(("2 wick", f"{'×3' if db.get('triple') else '×2'} L1 {db['low1']} · L2 {db['low2']}"))
    return tags


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sectors", default="", help="逗号分隔的XL板块代码（方法2选定的2个强势板块），如 XLV,XLY")
    args = ap.parse_args()
    sectors = [s.strip().upper() for s in args.sectors.split(",") if s.strip()]

    membership = load_etf_holdings()
    ctx = QuoteContext(Config.from_apikey_env())
    symbols = get_watchlist_symbols(ctx)
    print(f"watchlist US symbols: {len(symbols)}")
    if sectors:
        sector_syms = [tk + ".US" for tk, etfs in membership.items() if any(e in sectors for e in etfs)]
        before = len(symbols)
        symbols = sorted(set(symbols) | set(sector_syms))
        print(f"方法2板块下钻 {'+'.join(sectors)}: +{len(sector_syms)}只成分股（票池 {before}→{len(symbols)}）")
    results, errors = {}, []
    for i, sym in enumerate(symbols):
        try:
            bars = [{"date": str(b.timestamp.date()), "o": float(b.open), "h": float(b.high),
                     "l": float(b.low), "c": float(b.close), "v": b.volume}
                    for b in ctx.candlesticks(sym, Period.Day, 220, _ADJUST)]
            if len(bars) < 60 or bars[-1]["c"] < 3:
                continue
            m = analyze(bars)
            tags = classify(m)
            if tags:
                tk_plain = sym.replace(".US", "")
                results[tk_plain] = {
                    "sector_etfs": membership.get(tk_plain, []),
                    "setups": [{"type": t, "note": n} for t, n in tags],
                    "close": m["close"], "t1_pct": m["t1_pct"], "d5_pct": m["d5_pct"], "rsi14": m["rsi14"],
                    "dist_ema9_pct": m["dist_ema9_pct"], "dist_ma20_atr": m["dist_ma20_atr"],
                    "dist_ma50_pct": m["dist_ma50_pct"], "vol_ratio": m["vol_ratio"],
                    "range_pos": m["range_pos"], "atr14": m["atr14"],
                    "range5_pct": m["range5_pct"], "double_bottom": m.get("double_bottom"),
                    "data_date": m["date"],
                }
        except Exception as e:
            errors.append(f"{sym}: {e}")
        if i % 20 == 19:
            time.sleep(0.5)
    out = ROOT / "data" / "cache" / f"setups_{date.today():%Y%m%d}.json"
    json.dump({"scanned": len(symbols), "hits": results, "errors": errors[:20]},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {out}  (setups on {len(results)} tickers, {len(errors)} errors)")
    for tk, r in sorted(results.items(), key=lambda kv: -(kv[1]["rsi14"] or 0)):
        # 🔴 2026-08-20：连接符从 "+" 改成 " · "。新标签里的 "shakeout+burst" 自带加号，
        #    再用 "+" 连接就成了 "pullback+shakeout+burst"，**分不出是两个标签还是三个**。
        tags = " · ".join(s["type"] for s in r["setups"])
        print(f"  {tk:6s} [{tags}] close={r['close']} RSI={r['rsi14']} "
              f"d9EMA={r['dist_ema9_pct']}% 20MA={r['dist_ma20_atr']}ATR vol={r['vol_ratio']}x | "
              + "；".join(s["note"] for s in r["setups"]))


if __name__ == "__main__":
    main()
