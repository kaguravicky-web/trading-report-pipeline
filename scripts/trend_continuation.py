#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trend Continuation 选股筛选（2026-08-13 建）。

来源：Vic 老师做的《Trend Continuation 交易教學》（21 页，整理 0x_Kiko，
方法框架参考 Kristjan Kullamägi / Qullamaggie 的趋势延续风格）。
Vic 2026-08-13：「这个文件是我老师做的，总结了我交易方法，其实很简单，全部在这里了」。

本模块把教材 **p16「收市後選股」那张清单**做成机器筛选——原文七问：

    1. 過去 1–3 個月是否有清晰 strong uptrend？
    2. 前段升幅是否至少約 30%，而不是緩慢爬升？
    3. Base 是否約 2 週至 2 個月？
    4. 是否有 higher lows、volatility contraction、量能收乾？
    5. 多數時間是否在上升中的 EMA10／EMA20 之上？
    6. 目前是第幾個 base？是否已有 significant reset？
    7. 是否出現 wedging up + KD overbought 警告？

🔴 **它跟我们原有的 A–E setup 标签是两套东西，不要混**：
   A–E 是「今天这根 bar 长什么样」（回踩/tight/undercut/突破回踩/shakeout+burst）；
   这套是「这只票配不配进候选池」——**先过这七条，再谈今天有没有买点**。
   教材 p2 的原话：「先排除不合格 setup；再辨認買入機會」——**顺序不能反**。

止损/仓位不在这里算，走 report_helpers.exec_rows()（2026-08-13 已按教材 p11 改成
上限 min(1×ATR, 1×ADR)、理想 0.5 ATR）。

用法：
    python scripts/trend_continuation.py                 # 扫 watchlist + ETF成分
    python scripts/trend_continuation.py --tickers ANET,AVGO
    python scripts/trend_continuation.py --min-score 5   # 只看 5 分以上
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# ---- 教材里的阈值，全部集中在这里，改参数只改这一处 ----
PRIOR_MOVE_MIN = 30.0      # p16：前段升幅至少约 30%
PRIOR_LOOKBACK = 65        # 1–3 个月 ≈ 21–65 个交易日
BASE_MIN_DAYS = 10         # p16：base 约 2 週（10 个交易日）
BASE_MAX_DAYS = 45         # p16：至 2 個月（约 45 个交易日）
RESET_DAYS = 40            # p7：约两个月的整固可 reset base 计数（取 40 日为实务门槛）
EMA_HOLD_MIN = 0.60        # p6/p16：「多數時間」在 EMA10/20 之上——取 60%
KD_OVERBOUGHT = 80.0       # p9：9 日 K、D 均在超买区
VOL_DRYUP_MAX = 0.85       # p5：整固后段成交量收乾（后 5 日均量 / base 均量）


def ema(vals, n):
    if not vals:
        return None
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def stoch_kd(bars, n=9, d=3):
    """9 日 KD（教材 p9 用的就是 9 日 K/D）。返回 (K, D)。"""
    if len(bars) < n + d:
        return None, None
    ks = []
    for i in range(len(bars) - d, len(bars)):
        seg = bars[i - n + 1:i + 1]
        hh = max(b["h"] for b in seg)
        ll = min(b["l"] for b in seg)
        ks.append(100.0 if hh == ll else (bars[i]["c"] - ll) / (hh - ll) * 100)
    return ks[-1], sum(ks) / len(ks)


def find_base(bars):
    """定位最近一段 base：从最后一根往回找「最高收盘」那根，它之后就是整固段。

    这是刻意做简单的——教材本身就是肉眼判断，机器只负责初筛。
    返回 (base_start_idx, base_bars)；base 至少 3 根才算。
    """
    if len(bars) < 15:
        return None, []
    # 在最近 BASE_MAX_DAYS+5 根里找最高的高点
    win = bars[-(BASE_MAX_DAYS + 5):]
    off = len(bars) - len(win)
    hi_i = max(range(len(win)), key=lambda i: win[i]["h"]) + off
    base = bars[hi_i:]
    if len(base) < 3:
        return None, []
    return hi_i, base


def count_bases(bars, base_start):
    """第几个 base（p7）。从趋势起点往后数「创新高后进入整固」的次数。

    reset 规则（p7）：足够长的整固（≥RESET_DAYS）可以重置计数。
    """
    seg = bars[:base_start + 1]
    if len(seg) < 20:
        return 1
    n, run_high, since_high = 1, seg[0]["h"], 0
    for b in seg[1:]:
        if b["h"] > run_high:
            if since_high >= RESET_DAYS:
                n = 1                      # 长整固 → reset
            elif since_high >= BASE_MIN_DAYS:
                n += 1                     # 一个完整的 base 结束
            run_high, since_high = b["h"], 0
        else:
            since_high += 1
    return n


def scan_one(ticker, bars):
    """对单只票跑完 p16 七问。返回 dict（含 score 0–7 与逐条明细）。"""
    if len(bars) < 30:
        return None
    closes = [b["c"] for b in bars]
    last = bars[-1]
    base_start, base = find_base(bars)
    if not base:
        return None
    base_days = len(base)

    # ② 前段升幅：base 起点之前 1–3 个月内的最低点 → base 起点的高点
    pre = bars[max(0, base_start - PRIOR_LOOKBACK):base_start + 1]
    prior_low = min(b["l"] for b in pre) if pre else None
    base_high = bars[base_start]["h"]
    prior_move = (base_high / prior_low - 1) * 100 if prior_low else 0.0

    # ④ higher lows / 波幅收窄 / 量能收乾
    half = max(2, base_days // 2)
    lows_1st = min(b["l"] for b in base[:half])
    lows_2nd = min(b["l"] for b in base[half:]) if base[half:] else lows_1st
    higher_lows = lows_2nd > lows_1st
    rng_1st = sum((b["h"] - b["l"]) / b["c"] for b in base[:half]) / half
    _tail = base[half:] or base[:half]
    rng_2nd = sum((b["h"] - b["l"]) / b["c"] for b in _tail) / len(_tail)
    vol_contract = rng_2nd < rng_1st
    base_vol = sum(b.get("v", 0) for b in base) / base_days
    tail_vol = sum(b.get("v", 0) for b in base[-5:]) / min(5, base_days)
    vol_dryup = bool(base_vol) and (tail_vol / base_vol) <= VOL_DRYUP_MAX

    # ⑤ EMA10/20 停留率（用 base 期间收盘在 EMA 之上的比例）
    hold10 = hold20 = 0
    for i in range(base_start, len(bars)):
        e10 = ema(closes[:i + 1][-40:], 10)
        e20 = ema(closes[:i + 1][-60:], 20)
        if e10 and bars[i]["c"] > e10:
            hold10 += 1
        if e20 and bars[i]["c"] > e20:
            hold20 += 1
    hold10 /= base_days
    hold20 /= base_days

    # ⑦ wedging up + KD 超买
    k, dv = stoch_kd(bars)
    kd_ob = bool(k and dv and k >= KD_OVERBOUGHT and dv >= KD_OVERBOUGHT)
    highs_rising = base[-1]["h"] > base[0]["h"]
    wedging = highs_rising and higher_lows and not vol_contract

    # ADR20
    seg = [b for b in bars[-20:] if b.get("l")]
    adr = sum((b["h"] / b["l"] - 1) * 100 for b in seg) / len(seg) if seg else None

    # 🔴 p3 的三分类：本教材**只讲 Trend Continuation**，另两类风险性质完全不同。
    #    「Bottom Bounce：急跌後的均值回歸／反轉，最大風險是趨勢尚未真正扭轉。」
    #    机器判据：现价距近 60 日最高点的距离。离高点太远 = 它在反弹，不是在延续。
    #    2026-08-13 首扫就抓到：LITE 距 50 日高 -16.1%、CIEN -30.5%——
    #    我此前把它们跟 ANET（-5.2%）一起叫「AI 网络层主线」，**混了两种 setup**。
    hi60 = max(b["h"] for b in bars[-60:])
    off_high = (last["c"] / hi60 - 1) * 100
    if off_high >= -8:
        kind = "Trend Continuation"
    elif off_high >= -20:
        kind = "Consolidation Breakout（较长平台，防供应回流）"
    else:
        kind = "🔴Bottom Bounce（趋势未必已扭转，不是本方法覆盖的类型）"

    checks = {
        "前段升幅≥30%": prior_move >= PRIOR_MOVE_MIN,
        "base 2周-2月": BASE_MIN_DAYS <= base_days <= BASE_MAX_DAYS,
        "higher lows": higher_lows,
        "波幅收窄": vol_contract,
        "量能收乾": vol_dryup,
        "EMA10/20停留≥60%": max(hold10, hold20) >= EMA_HOLD_MIN,
        "无wedging+KD超买": not (wedging and kd_ob),
    }
    return {
        "ticker": ticker, "close": round(last["c"], 2),
        "kind": kind, "off_60d_high_pct": round(off_high, 1),
        "score": sum(checks.values()), "checks": checks,
        "prior_move_pct": round(prior_move, 1),
        "base_days": base_days,
        "base_count": count_bases(bars, base_start),
        "ema10_hold": round(hold10 * 100), "ema20_hold": round(hold20 * 100),
        "kd_k": round(k, 1) if k else None, "kd_d": round(dv, 1) if dv else None,
        "wedging_up": wedging, "kd_overbought": kd_ob,
        "adr20_pct": round(adr, 2) if adr else None,
        "failed": [k2 for k2, v in checks.items() if not v],
    }


def main():
    import fetch_market_data as F
    from longport.openapi import QuoteContext, Config

    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="")
    ap.add_argument("--min-score", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    ctx = QuoteContext(Config.from_apikey_env())
    if a.tickers:
        syms = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    else:
        syms = sorted({r["ticker"] for r in _universe(ctx)})
    if a.limit:
        syms = syms[:a.limit]
    print(f"扫描 {len(syms)} 只（p16 七问，min-score={a.min_score}）...")

    out = []
    for i, t in enumerate(syms, 1):
        try:
            bars = F.fetch_bars(ctx, t, 130)
        except Exception:
            continue
        if not bars:
            continue
        r = scan_one(t, bars)
        if r:
            out.append(r)
        if i % 50 == 0:
            print(f"  ...{i}/{len(syms)}")

    out.sort(key=lambda r: (-r["score"], -r["prior_move_pct"]))
    p = ROOT / f"data/cache/tc_scan_{date.today():%Y%m%d}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {p}  （{len(out)} 只有效）\n")

    hits = [r for r in out if r["score"] >= a.min_score]
    print(f"{'TICKER':<7}{'分':<5}{'距60日高':<10}{'类型':<34}{'前段升幅':<10}"
          f"{'base日':<8}{'第几':<6}{'EMA停留':<9}{'ADR%':<7}未过项")
    for r in hits[:40]:
        print(f"{r['ticker']:<7}{r['score']}/7  {r['off_60d_high_pct']:>7.1f}% "
              f"{r['kind']:<34}{r['prior_move_pct']:>7.1f}% "
              f"{r['base_days']:>5}日 {r['base_count']:>4} "
              f"{max(r['ema10_hold'], r['ema20_hold']):>6}% {r['adr20_pct'] or 0:>6.2f} "
              f"{'、'.join(r['failed']) or '全过'}")


def _universe(ctx=None):
    """watchlist + ETF_Holdings 成分股 + 当前持仓——跟 scan_setups 同一个票池口径。

    🔴 2026-08-13 首版只读了 ETF_Holdings（730 只），**漏了 LongBridge watchlist**——
    跟 2026-07-15「followed universe 光靠 watchlist+持仓漏了 GS/IBM/ISRG」是同一类错，
    只是方向反过来。两边都要。
    """
    import csv
    syms = set()
    p = ROOT / "reference/ETF_Holdings.csv"
    if p.exists():
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            t = (r.get("Ticker") or "").strip().upper()
            if t and "." not in t:
                syms.add(t)
    if ctx is not None:
        try:
            for group in ctx.watchlist():
                for s in group.securities:
                    if s.symbol.endswith(".US"):
                        syms.add(s.symbol[:-3])
        except Exception as e:
            print(f"⚠️ watchlist 取不到（{e}），本次只用 ETF_Holdings")
    try:
        import report_helpers as H
        syms |= {p["ticker"] for p in H.load_tradebook_positions()}
    except Exception:
        pass
    return [{"ticker": t} for t in sorted(syms)]


if __name__ == "__main__":
    main()
