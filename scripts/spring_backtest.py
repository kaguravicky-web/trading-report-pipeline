#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指数级 spring / FTD 面板回测（2026-08-05 建，源自 Vic 两个连续的质疑）。

**质疑一**（2026-08-05）：「过去的FTD教科书可能已经不能用了，现在都是量化，
很容易 liquidity grab 打止损，然后再爆啦」。
  → Vic 给的 spring 定义：扫破**过去14个交易日**最低 → 第二天或第三天收盘拉回该低点上方。
  → 结论：spring 太常见（67~77%）没有筛选性；早进的代价在 +10/+20 日显现。
     **定案：spring=预警不下单，FTD=建仓1/3 starter**（Vic 批准）。

**质疑二**（同日，更关键）：「单看 SMH 和 QQQ 是用 FTD，但是结合标普和 IWM 道指和个股，
结论就会不同了」。
  → 实测成立：2026-08-03 收盘 DIA/QQQE/XLI/XLK 四个同时满足 FTD 两条件，
     而当时面板只有 QQQ/VOO，两个都因量不够被判 fail——**确认信号被面板选择耽误了一天**。
  → 根因：QQQ/VOO 都是市值加权，成交量被少数大票的换手掩盖；QQQE(纳指等权)8/3 量 1.65×
     是全场最高，说明真实买盘在中小票上。且 O'Neil 原版用的是 Nasdaq **Composite**(3000+只)，
     我们拿 QQQ(100只市值加权)代理，代理本身就有偏差。

用法：
    python scripts/spring_backtest.py              # 全部三段
    python scripts/spring_backtest.py --panel      # 只跑 FTD 面板对比
"""
import sys, statistics, argparse
sys.stdout.reconfigure(encoding="utf-8")
from longport.openapi import QuoteContext, Config, Period, AdjustType

# 🔴 K线复权口径统一走 fetch_market_data.BARS_ADJUST（2026-08-19 定）——
#    这里原本写死 NoAdjust，窗口跨过拆股就整段作废（CRWD 距50MA 报 -42% 真值 +11%）。
import report_helpers as _H  # noqa: E402
_ADJUST = _H.bars_adjust()

LOOKBACK = 14
FWD = (5, 10, 20)
PANEL = ["QQQ", "VOO", "IWM", "DIA", "RSP", "QQQE"]
NARROW = ["QQQ", "VOO"]
BARS = 900

ctx = QuoteContext(Config.from_apikey_env())
_cache = {}


def bars_of(tk, n=BARS):
    if tk in _cache:
        return _cache[tk]
    bs = ctx.candlesticks(f"{tk}.US", Period.Day, n, _ADJUST)
    r = [{"d": str(b.timestamp)[:10], "h": float(b.high), "l": float(b.low),
          "c": float(b.close), "v": float(b.volume)} for b in bs]
    _cache[tk] = r
    return r


def stat(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return "—"
    win = sum(1 for x in v if x > 0) / len(v) * 100
    return "n=%-3d 胜率%3.0f%% 均值%+6.2f%% 中位%+6.2f%%" % (
        len(v), win, statistics.mean(v), statistics.median(v))


def is_ftd_bar(rows, i, vol="up"):
    """单日是否达标。
    vol="up"   涨幅≥1.25% 且 量>前一日   （O'Neil 原版：要看到机构真金白银在买）
    vol="any"  只看涨幅，不管量
    vol="down" 涨幅≥1.25% 且 量<前一日   （Vic 2026-08-05 假设：缩量上涨=去杠杆已完成、
                                          卖盘枯竭，是高质量上涨。同源理论=Wyckoff「no supply」、
                                          Minervini VDU、Deemer「lack of declines」）
    """
    if i == 0:
        return False
    pct = (rows[i]["c"] / rows[i - 1]["c"] - 1) * 100
    if pct < 1.25:
        return False
    if vol == "any":
        return True
    if vol == "down":
        return rows[i]["v"] < rows[i - 1]["v"]
    return rows[i]["v"] > rows[i - 1]["v"]


def spring_events(tk):
    """返回 [(d0_idx, reclaim_idx or None)]，同一段下跌只取一次。"""
    B = bars_of(tk)
    ev, i = [], LOOKBACK
    while i < len(B) - 1:
        lvl = min(b["l"] for b in B[i - LOOKBACK:i])
        if B[i]["l"] >= lvl:
            i += 1
            continue
        rec = None
        for k in (1, 2):
            if i + k < len(B) and B[i + k]["c"] > lvl:
                rec = i + k
                break
        ev.append((i, rec))
        i = (rec if rec is not None else i) + LOOKBACK
    return B, ev


def part1_spring():
    print("=" * 88)
    print("【一】spring（扫破14日低点 + 2天内拉回）单独用作入场信号")
    for tk in ("QQQ", "VOO", "IWM"):
        B, ev = spring_events(tk)
        sp = [r for _, r in ev if r is not None]
        print("\n%s  %s→%s  扫破 %d 次 / 2天内拉回 %d 次 = %.0f%%"
              % (tk, B[0]["d"], B[-1]["d"], len(ev), len(sp), len(sp) / max(1, len(ev)) * 100))
        for w in FWD:
            print("    +%2d日 %s" % (w, stat([(B[r + w]["c"] / B[r]["c"] - 1) * 100
                                              if r + w < len(B) else None for r in sp])))


def part2_panel():
    """同一批 rally attempt 上，比较三种 FTD 面板口径的入场表现。"""
    print("=" * 88)
    print("【二】FTD 面板口径对比（rally attempt 以 VOO 扫破14日低点定义 D0）")
    Bv, ev = spring_events("VOO")
    dates = [b["d"] for b in Bv]
    idx = {d: i for i, d in enumerate(dates)}
    panels = {t: bars_of(t) for t in PANEL}
    pidx = {t: {b["d"]: i for i, b in enumerate(panels[t])} for t in PANEL}

    def day1_of(d0_i):
        """Day 1 代理 = D0 之后第一根收阳的bar（Vic 肉眼那一步无法回溯，只能代理）。"""
        for k in range(1, 8):
            j = d0_i + k
            if j >= len(dates):
                return None
            if Bv[j]["c"] > Bv[j - 1]["c"]:
                return j
        return None

    def first_ftd(d0_i, tickers, need, window=True, vol="up"):
        """首个「至少 need 只面板成员同日达标」的日子。
        window=True 时套用 O'Neil 的 Day 4-7 窗口（Day 1 = 上面的代理）。"""
        d1 = day1_of(d0_i) if window else None
        if window and d1 is None:
            return None
        lo, hi = (d1 + 3, d1 + 6) if window else (d0_i + 1, d0_i + 10)
        for j in range(lo, hi + 1):
            if j >= len(dates):
                return None
            d = dates[j]
            hit = sum(1 for t in tickers
                      if pidx[t].get(d) is not None and is_ftd_bar(panels[t], pidx[t][d], vol))
            if hit >= need:
                return j
        return None

    print("\n" + "-" * 84)
    print("  【量的条件怎么用——Vic 2026-08-05 假设：缩量上涨=去杠杆完成=高质量】")
    print("  面板固定为六只任一 + Day 4-7 窗口，只换量的条件")
    for vname, vol in [("量>前日（O'Neil原版）", "up"),
                       ("不看量，只要涨幅够", "any"),
                       ("量<前日（缩量上涨）", "down")]:
        entries, lags = [], []
        for d0_i, _ in ev:
            j = first_ftd(d0_i, PANEL, 1, window=True, vol=vol)
            if j is None:
                continue
            entries.append(j)
            lags.append(j - d0_i)
        print("\n  %-22s 触发 %d/%d 次   滞后中位 %s"
              % (vname, len(entries), len(ev),
                 ("%.0f" % statistics.median(lags)) if lags else "—"))
        for w in FWD:
            print("      +%2d日 %s" % (w, stat([(Bv[j + w]["c"] / Bv[j]["c"] - 1) * 100
                                                if j + w < len(Bv) else None for j in entries])))

    print("\n" + "-" * 84)
    print("  【缩量出现在哪个位置——把 Vic 的假设放到 Day 2-3 上重测】")
    print("  同一批 FTD 入场（六只任一+窗口+量>前日），按「Day 2-3 是否缩量」分两组")
    quiet, loud = [], []
    for d0_i, _ in ev:
        j = first_ftd(d0_i, PANEL, 1, window=True, vol="up")
        d1 = day1_of(d0_i)
        if j is None or d1 is None or d1 + 2 >= len(dates):
            continue
        vr23 = [Bv[k]["v"] / Bv[k - 1]["v"] for k in (d1 + 1, d1 + 2)]
        (quiet if sum(vr23) / 2 < 1.0 else loud).append(j)
    for nm, grp in [("Day2-3 缩量（无供给）", quiet), ("Day2-3 放量", loud)]:
        print("\n  %-22s n=%d" % (nm, len(grp)))
        for w in FWD:
            print("      +%2d日 %s" % (w, stat([(Bv[j + w]["c"] / Bv[j]["c"] - 1) * 100
                                                if j + w < len(Bv) else None for j in grp])))

    print("\n" + "-" * 84)
    modes = [("现行：QQQ/VOO 任一", NARROW, 1),
             ("扩面板：6只任一", PANEL, 1),
             ("扩面板：6只≥2", PANEL, 2),
             ("扩面板：6只≥3", PANEL, 3)]
    for win in (False, True):
        print("\n" + ("-" * 84))
        print("  【%s】" % ("套用 O'Neil Day 4-7 窗口（与实装口径一致）" if win
                            else "不套窗口：D0后10日内首个达标日（2026-08-05首版口径）"))
        for name, tks, need in modes:
            entries, lags = [], []
            for d0_i, _ in ev:
                j = first_ftd(d0_i, tks, need, window=win)
                if j is None:
                    continue
                entries.append(j)
                lags.append(j - d0_i)
            print("\n  %-22s 触发 %d/%d 次   入场滞后中位 %s 个交易日"
                  % (name, len(entries), len(ev),
                     ("%.0f" % statistics.median(lags)) if lags else "—"))
            for w in FWD:
                print("      +%2d日 %s" % (w, stat([(Bv[j + w]["c"] / Bv[j]["c"] - 1) * 100
                                                    if j + w < len(Bv) else None for j in entries])))


def part3_recent():
    print("=" * 88)
    print("【三】2026-07-29 起逐日面板明细（当期案例）")
    show = ["2026-07-29", "2026-07-30", "2026-07-31", "2026-08-03", "2026-08-04"]
    print("%-6s" % "" + "".join("%17s" % d[5:] for d in show))
    for t in PANEL + ["SMH", "XLK", "XLI"]:
        rows = bars_of(t)
        m = {b["d"]: i for i, b in enumerate(rows)}
        line = "%-6s" % t
        for d in show:
            i = m.get(d)
            if i is None or i == 0:
                line += "%17s" % "-"
                continue
            pct = (rows[i]["c"] / rows[i - 1]["c"] - 1) * 100
            vr = rows[i]["v"] / rows[i - 1]["v"]
            tag = "FTD" if is_ftd_bar(rows, i) else ("量✗" if pct >= 1.25 else "")
            line += "%17s" % ("%+.2f%% %.2fx %s" % (pct, vr, tag))
        print(line)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", action="store_true", help="只跑面板对比")
    a = ap.parse_args()
    if not a.panel:
        part1_spring()
    part2_panel()
    part3_recent()
