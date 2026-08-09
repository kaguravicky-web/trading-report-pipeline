#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前快照：LongBridge watchlist全量US标的 + reference/ETF_Holdings.csv全部成分股 + 持仓票的盘前价，
写 data/cache/premarket_YYYYMMDD.json。（2026-07-15 Vic：Premarket movers扫描范围加上ETF holdings持仓；
同日再加：持仓票强制并入+专属低门槛警报——SYK教训：盘前量很大但价格没到7%门槛，完全静默，当天暴跌）

格式与report_helpers.load_premarket_snap一致：
  {ticker: {close, pm, pm_pct, pm_vol, pm_stale, vol20, vol_ratio_pm, position, pos_alert}}
pm_stale=True 表示pre_market_quote的timestamp日期不是今天（残留上一时段旧数据，
2026-07-11教训：必须校验，否则涨跌方向都可能算反）。
vol20/vol_ratio_pm 对两类标的计算（全量symbol都拉20日均量太贵）：
  ①达到MOVER门槛（|盘前%|≥min_move）的——区分"大量涨"还是"量很低"
  ②持仓票（positions.json里非CLOSED的）——**无条件计算**，持仓的盘前异动信号主要在量不在价
持仓票专属警报（pos_alert=True）：数据新鲜且（|盘前%|≥3 或 量比≥10%）任一触发——
门槛远低于MOVER的7%，因为持仓的风险容忍度和"错过的代价"跟找新机会完全不同。

用法： python scripts/snap_premarket.py [--min-move 7]
输出：先打【持仓盘前雷达】（每只持仓必列，触发的标🔴），再按|盘前%|降序列MOVER Top20（附量比）。
"""
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent

from longport.openapi import AdjustType, Config, Period, QuoteContext


def get_watchlist_symbols(ctx):
    symbols = []
    for group in ctx.watchlist():
        for s in group.securities:
            if s.symbol.endswith(".US"):
                symbols.append(s.symbol)
    return sorted(set(symbols))


def get_position_tickers():
    """当前持仓票（2026-07-15加，SYK教训：持仓必须无条件进盘前扫描）。
    2026-07-16起改读data/tradebook.json（Vic："以后持仓，只扫描我的tradebook"）——
    data/positions.json不再维护，继续读它会让新仓漏出盘前扫描范围。"""
    p = ROOT / "data" / "tradebook.json"
    if not p.exists():
        return []
    trades = json.load(open(p, encoding="utf-8")).get("trades", [])
    return sorted({t["ticker"] for t in trades
                   if t.get("status") == "open" and t.get("ticker") and "." not in t["ticker"]})


def get_etf_holdings_symbols():
    """reference/ETF_Holdings.csv全部成分股（2026-07-15加入扫描范围）。
    只收纯字母1-5位的美股代码：过滤外国上市（.KS/.TO/.PA等）、BRK.B类带点美股
    （LongBridge symbol校验过不了）、以及-USDCASH-/2602335D之类的现金行和占位符。"""
    import csv
    import re
    path = ROOT / "reference" / "ETF_Holdings.csv"
    if not path.exists():
        return []
    out = set()
    for row in csv.DictReader(open(path, encoding="utf-8-sig")):
        tk = (row.get("Ticker") or "").strip()
        if re.fullmatch(r"[A-Z]{1,5}", tk):
            out.add(tk + ".US")
    return sorted(out)


def main():
    min_move = 7.0
    if "--min-move" in sys.argv:
        min_move = float(sys.argv[sys.argv.index("--min-move") + 1])
    today = date.today()
    ctx = QuoteContext(Config.from_apikey_env())
    wl = get_watchlist_symbols(ctx)
    holdings = get_etf_holdings_symbols()
    pos_tickers = get_position_tickers()
    symbols = sorted(set(wl) | set(holdings) | {t + ".US" for t in pos_tickers})
    print(f"watchlist US symbols: {len(wl)}  + ETF holdings: {len(holdings)}  + 持仓: {len(pos_tickers)}  → 合计去重: {len(symbols)}")

    def quote_batch(batch):
        """一批里混进无效/退市代码时不能毁掉整批：整批失败就对半拆重试，单只失败丢弃。"""
        try:
            return ctx.quote(batch)
        except Exception:
            if len(batch) == 1:
                return []
            mid = len(batch) // 2
            return list(quote_batch(batch[:mid])) + list(quote_batch(batch[mid:]))

    snap = {}
    for i in range(0, len(symbols), 100):  # quote()一次最多500，稳妥按100切
        batch = symbols[i:i + 100]
        for q in quote_batch(batch):
            tk = q.symbol[:-3]
            close = float(q.last_done) if q.last_done else None
            pmq = q.pre_market_quote
            if not pmq or not pmq.last_done or not close:
                continue
            ts = pmq.timestamp
            stale = (ts.date() != today) if isinstance(ts, datetime) else True
            pm = float(pmq.last_done)
            snap[tk] = {
                "close": close,
                "pm": pm,
                "pm_pct": round((pm / close - 1) * 100, 2),
                "pm_vol": int(pmq.volume or 0),
                "pm_stale": stale,
            }

    fresh = {k: v for k, v in snap.items() if not v["pm_stale"]}
    mover_tickers = [tk for tk, v in fresh.items() if abs(v["pm_pct"]) >= min_move]
    # 量比计算对象 = MOVER ∪ 持仓票（持仓无条件算——SYK教训：持仓的盘前异动信号主要在量不在价）
    vol_targets = sorted(set(mover_tickers) | {t for t in pos_tickers if t in snap})
    print(f"MOVER门槛|{min_move}%|+: {len(mover_tickers)}只 + 持仓{len([t for t in pos_tickers if t in snap])}只，逐只拉20日均量算量比 ...")
    for tk in vol_targets:
        v = snap[tk]
        v["vol20"], v["vol_ratio_pm"] = None, None
        try:
            bars = ctx.candlesticks(f"{tk}.US", Period.Day, 21, AdjustType.NoAdjust)
            vols = [float(str(b.volume)) for b in bars if b.volume]
            if len(vols) >= 15:  # 新股/停牌股可能凑不满21根，15根起也能算个粗略基准
                vol20 = sum(vols) / len(vols)
                v["vol20"] = round(vol20)
                v["vol_ratio_pm"] = round(v["pm_vol"] / vol20, 3) if vol20 else None
        except Exception as e:
            print(f"  [vol20 skip] {tk}: {e}")
        time.sleep(0.1)

    # 持仓票专属警报：门槛远低于MOVER（|盘前%|≥3 或 量比≥10%），数据必须新鲜
    POS_MOVE_PCT, POS_VOL_RATIO = 3.0, 0.10
    for tk in pos_tickers:
        v = snap.get(tk)
        if not v:
            continue
        v["position"] = True
        vr = v.get("vol_ratio_pm")
        v["pos_alert"] = bool(not v["pm_stale"] and (
            abs(v["pm_pct"]) >= POS_MOVE_PCT or (vr is not None and vr >= POS_VOL_RATIO)))

    out = ROOT / "data" / "cache" / f"premarket_{today.strftime('%Y%m%d')}.json"
    json.dump(snap, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    stale_n = len(snap) - len(fresh)
    print(f"wrote {out}  (fresh={len(fresh)}, stale丢弃展示={stale_n})")

    # 持仓盘前雷达永远最先打、每只必列——"我没发现"不允许再发生（2026-07-15 SYK教训）
    print(f"\n【持仓盘前雷达】（警报门槛：|盘前%|≥{POS_MOVE_PCT} 或 量比≥{POS_VOL_RATIO*100:.0f}%）:")
    for tk in pos_tickers:
        v = snap.get(tk)
        if not v:
            print(f"  {tk:6s} 无盘前quote")
            continue
        vr = v.get("vol_ratio_pm")
        vr_s = f"量比={vr*100:.1f}%" if vr is not None else "量比=-"
        stale_s = "（旧数据，忽略）" if v["pm_stale"] else ""
        tag = "  <-- 🔴 POSITION-ALERT" if v.get("pos_alert") else ""
        print(f"  {tk:6s} pm={v['pm']:<9.2f} {v['pm_pct']:+.2f}%  vol={v['pm_vol']}  {vr_s}{stale_s}{tag}")

    movers = sorted(fresh.items(), key=lambda kv: -abs(kv[1]["pm_pct"]))
    print(f"\n盘前异动 |{min_move}%|+ (MOVER) 及 Top20（量比=盘前量/20日均量，>=20%算放量，<5%算低量）:")
    for tk, v in movers[:20]:
        tag = "  <-- MOVER" if abs(v["pm_pct"]) >= min_move else ""
        vr = v.get("vol_ratio_pm")
        vr_s = f"  量比={vr*100:.1f}%" if vr is not None else ""
        print(f"  {tk:6s} pm={v['pm']:<9.2f} {v['pm_pct']:+.2f}%  vol={v['pm_vol']}{vr_s}{tag}")


if __name__ == "__main__":
    main()
