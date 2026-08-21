#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓跟踪线选择：EMA10 还是 EMA20（2026-08-13 建）。

来源：Vic 老师《Trend Continuation 交易教學》p14「持倉管理」——

    「第 3–5 日可按規則賣出 1/3 至 1/2，並把餘倉止損移至損益平衡。」
    「餘下倉位選用 EMA10 或 EMA20 跟蹤，**選定後保持一致**。」
    「以**首次收盤跌破所選均線**作退出參考，不因盤中短暫刺穿而情緒化反應。」
    「快速股票通常使用較緊的 EMA10；較慢趨勢可考慮 EMA20。」

🔴 **「保持一致」是指同一笔仓位选定后别中途改，不是所有票用同一条。**
   （Claude 2026-08-13 一度读成「全局选一条」，Vic 当场纠正：
    「需要观察哪条线有支撑，每个股不同的，一定要统一嘛？」——他是对的，教材第四句明说按快慢分。）

**那怎么不靠肉眼？让这只票自己的历史来决定。**
做法：在当前这一段上升腿里，把教材的退出规则**两条都回测一遍**——
「首次收盘跌破 EMA10 就出」vs「首次收盘跌破 EMA20 就出」，看各自能吃到这段行情的多少。
再数一次「跌破 EMA10 但趋势其实还在」的次数——次数多，说明 EMA10 对这只票就是噪音。

用法：
    python scripts/ema_trail.py                    # 扫全部持仓
    python scripts/ema_trail.py --tickers ANET,TER
"""
import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LEG_LOOKBACK = 70          # 找当前上升腿的回看窗口（约 3 个月）
NOISE_MARGIN = 0.03        # 跌破后 10 日内涨回 +3% 以上 → 那次跌破算噪音


def ema_series(vals, n):
    k = 2 / (n + 1)
    out, e = [], vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def analyze(ticker, bars):
    """返回该票的跟踪线建议 + 证据。"""
    if len(bars) < LEG_LOOKBACK:
        return None
    closes = [b["c"] for b in bars]
    e10 = ema_series(closes, 10)
    e20 = ema_series(closes, 20)

    # 当前上升腿起点：回看窗口内的最低收盘
    win_start = len(bars) - LEG_LOOKBACK
    leg_start = min(range(win_start, len(bars)), key=lambda i: closes[i])
    if leg_start >= len(bars) - 5:            # 腿太短，说明还在下跌里
        return None
    entry = closes[leg_start]
    peak = max(closes[leg_start:])
    now = closes[-1]

    def backtest(ema):
        """按教材 p14 回测「首次收盘跌破就出」。返回 (吃到%, 出场第几天, 是否还在场内)。

        🔴 起点不能用腿的最低点：那时价格本来就在均线下方，第一根就触发退出，
        测出来全是「D1 出」（2026-08-13 首版就是这个 bug，18 只里 11 只无意义）。
        **教材那条规则是用在已经站上均线的盈利仓位上的**——所以跟踪从
        「腿开始后第一次收盘站上该均线」那天起算。
        """
        start = None
        for i in range(leg_start, len(bars)):
            if closes[i] > ema[i]:
                start = i
                break
        if start is None:
            return None, None, False
        base = closes[start]
        for i in range(start + 1, len(bars)):
            if closes[i] < ema[i]:
                return (closes[i] / base - 1) * 100, i - start, False
        return (now / base - 1) * 100, len(bars) - 1 - start, True

    cap10, day10, hold10 = backtest(e10)
    cap20, day20, hold20 = backtest(e20)
    full = (peak / entry - 1) * 100          # 这段腿的理论最大涨幅

    # 「跌破但趋势还在」的次数 = 噪音跌破
    def noise_breaks(ema):
        n = 0
        for i in range(leg_start + 1, len(bars) - 10):
            if closes[i] < ema[i] and closes[i - 1] >= ema[i - 1]:
                if max(closes[i:i + 10]) / closes[i] - 1 >= NOISE_MARGIN:
                    n += 1
        return n

    nb10, nb20 = noise_breaks(e10), noise_breaks(e20)

    if cap10 is None or cap20 is None:
        return None

    # 建议：谁吃到的多用谁；差距 <3pt 时用噪音跌破次数打破平局（少的赢）
    if abs(cap10 - cap20) < 3:
        pick = "EMA20" if nb10 > nb20 else "EMA10"
        why = f"两条吃到的差不多（{cap10:+.1f}% vs {cap20:+.1f}%），按噪音跌破次数取少的"
    elif cap10 > cap20:
        pick = "EMA10"
        why = f"EMA10 吃到 {cap10:+.1f}%，EMA20 只有 {cap20:+.1f}%"
    else:
        pick = "EMA20"
        why = f"EMA20 吃到 {cap20:+.1f}%，EMA10 只有 {cap10:+.1f}%"

    cur = e10[-1] if pick == "EMA10" else e20[-1]
    return {
        "ticker": ticker, "close": round(now, 2), "pick": pick, "why": why,
        "line_now": round(cur, 2), "dist_pct": round((now / cur - 1) * 100, 2),
        "leg_days": len(bars) - 1 - leg_start, "leg_full_pct": round(full, 1),
        "cap10": round(cap10, 1), "cap20": round(cap20, 1),
        "day10": day10, "day20": day20, "hold10": hold10, "hold20": hold20,
        "noise10": nb10, "noise20": nb20,
        "ema10": round(e10[-1], 2), "ema20": round(e20[-1], 2),
    }


def main():
    import report_helpers as H
    import fetch_market_data as F
    from longport.openapi import QuoteContext, Config

    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="")
    a = ap.parse_args()

    syms = ([t.strip().upper() for t in a.tickers.split(",") if t.strip()]
            if a.tickers else sorted({p["ticker"] for p in H.load_tradebook_positions()}))
    ctx = QuoteContext(Config.from_apikey_env())

    rows = []
    for t in syms:
        try:
            bars = F.fetch_bars(ctx, t, 130)
        except Exception:
            continue
        r = analyze(t, bars) if bars else None
        if r:
            rows.append(r)

    print(f"\n{'TICKER':<7}{'建议':<8}{'线位':<9}{'距线':<9}{'腿长':<7}{'整段':<8}"
          f"{'EMA10吃到':<11}{'EMA20吃到':<11}{'噪音破线(10/20)':<16}")
    for r in rows:
        h10 = "持有中" if r["hold10"] else f"D{r['day10']}出"
        h20 = "持有中" if r["hold20"] else f"D{r['day20']}出"
        print(f"{r['ticker']:<7}{r['pick']:<8}{r['line_now']:<9.2f}{r['dist_pct']:>+7.2f}% "
              f"{r['leg_days']:>4}日 {r['leg_full_pct']:>6.1f}% "
              f"{r['cap10']:>+7.1f}%({h10:<6}) {r['cap20']:>+7.1f}%({h20:<6}) "
              f"{r['noise10']:>3} / {r['noise20']:<3}")
    print("\n口径：从近 70 日最低收盘起算为「当前上升腿」；两条线各自按教材"
          "「首次收盘跌破就出」回测；噪音破线 = 跌破后 10 日内又涨回 +3% 以上的次数。")
    print("🔴 选定后写进 tradebook 那笔，**中途不改**——这是教材 p14「選定後保持一致」的原意。")
    return rows


if __name__ == "__main__":
    main()
