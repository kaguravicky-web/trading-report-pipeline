#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财报日历扫描（2026-07-15新增，Vic抓到偷懒第三次——"财报扫描你不要偷懒，现在是财报季"。
ISRG/IBM/GS当天只是恰好被点名/搜到，不是主动扫描的结果，漏了/记错了ISRG实际报告日期。

用Nasdaq公开财报日历API（无需登录/无需key，跟本项目其他公开数据源同一套路子）拿"今天全市场
谁要报财报"，跟followed universe（LongBridge watchlist+持仓+ML Leader+防御篮子）取交集——
一次API调用返回当天全部财报，交集是本地集合运算，不产生按ticker轮询的成本，可以放心天天跑全量。

用法：
    python scripts/fetch_earnings_calendar.py                    # 今天+未来6天（盘前用，看本周谁要报）
    python scripts/fetch_earnings_calendar.py --date 2026-07-14  # 只查这一天（盘后回溯当天用）
输出：data/cache/earnings_calendar_YYYYMMDD.json + 终端摘要
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def fetch_day(d: str) -> list:
    import urllib.request
    req = urllib.request.Request(
        f"https://api.nasdaq.com/api/calendar/earnings?date={d}",
        headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                 "Referer": "https://www.nasdaq.com/market-activity/earnings"})
    try:
        raw = json.loads(urllib.request.urlopen(req, timeout=20).read())
        return (raw.get("data") or {}).get("rows") or []
    except Exception as e:
        print(f"  [skip] {d}: {e}")
        return []


# 🔴 主线读数股（2026-08-19 加，事故驱动）。
# 事故：Fabrinet(FN) 2026-08-17 盘后发财报，营收/EPS 都超预期但毛利、自由现金流和下季利润指引不行，
# 盘后先跌 ~7%、8/18 收跌 **-19.38%**，把整层 AI 光连接拖下水（AAOI -15.16%，同日 Vic 还日内做了两笔），
# 也是 SMH 当天 -4.09% 丢掉 50MA 的直接推手之一。
# **而 FN 在 8/17、8/18 两份财报日历里一次都没出现过**——因为 followed universe =
# 持仓 + ML Leader + 防御篮子 + XL 板块成分；FN 是标普中盘股，三样都不沾。
# 两个结构性缺口：
#   ①票池只认「已经买了的」——**清仓之后财报雷达跟着一起清空**，恰恰是最需要盯住刚退出那一层的时候；
#   ②一层里真正定价的往往是上游/代工（光模块看 FN、设备看 AMAT/LRCX），它们不在任何一只 XL 成分里。
# 所以票池要额外常驻这批「读数股」：不持有也要知道它们哪天报、报完那层怎么走。
READTHROUGH = [
    # 光通信 / AI 连接（FN 是整层的代工枢纽）
    "FN", "COHR", "LITE", "AAOI", "CRDO", "ALAB",
    # 半导体设备 / 测试
    "AMAT", "LRCX", "KLAC", "ASML", "TER", "KEYS", "ADI",
    # 存储
    "MU", "SNDK", "WDC", "STX",
    # AI 算力主线
    "NVDA", "AVGO", "MRVL", "AMD", "TSM", "SMCI", "DELL", "ANET",
]


def load_universe() -> set:
    """watchlist + 持仓 + ML Leader + 防御篮子 + ETF_Holdings.csv全部成分股——跟snap_premarket.py的
    Premarket Movers扫描范围同一套逻辑（2026-07-15 Vic扩大过一次）。**必须包含ETF_Holdings**：
    首次实测只用watchlist+持仓+ML Leader时，GS/IBM/ISRG全部漏网（248只里0命中）——这三只当天恰好
    是市场级新闻/板块联动的关键标的，但都不在watchlist里，只靠"Vic提到才查"这种被动模式正是
    "偷懒"被抓的那种缺口。ETF_Holdings覆盖11个XL板块全部成分股，把GS(XLF)/IBM(XLK)/ISRG(XLV)
    这类不在个人watchlist但对板块叙事重要的大盘股全部纳入扫描范围。"""
    import csv
    import re
    tickers = set()
    # 2026-07-16起改读data/tradebook.json（Vic："以后持仓，只扫描我的tradebook"）——
    # data/positions.json不再维护，继续读它会让新仓漏出followed universe
    tb = json.loads((ROOT / "data" / "tradebook.json").read_text(encoding="utf-8"))
    tickers |= {t["ticker"] for t in tb.get("trades", []) if t.get("status") == "open" and t.get("ticker")}

    sys.path.insert(0, str(ROOT / "scripts"))
    import fetch_market_data as F
    tickers |= set(F.ML_LEADERS) | set(F.DEFENSIVE) | set(F.LAODENG)
    tickers |= set(READTHROUGH)   # 主线读数股常驻，不随持仓增减（2026-08-19，FN 事故）

    holdings_path = ROOT / "reference" / "ETF_Holdings.csv"
    if holdings_path.exists():
        for row in csv.DictReader(open(holdings_path, encoding="utf-8-sig")):
            tk = (row.get("Ticker") or "").strip()
            if re.fullmatch(r"[A-Z]{1,5}", tk):
                tickers.add(tk)

    try:
        from longport.openapi import QuoteContext, Config
        ctx = QuoteContext(Config.from_apikey_env())
        for group in ctx.watchlist():
            for s in group.securities:
                if s.symbol.endswith(".US"):
                    tickers.add(s.symbol[:-3])
    except Exception as e:
        print(f"  [watchlist skip] {e}")
    return tickers


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="只查这一天（YYYY-MM-DD），默认今天+未来6天")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    universe = load_universe()
    print(f"followed universe: {len(universe)}只（watchlist+持仓+ML Leader+防御篮子）")

    if args.date:
        dates = [args.date]
    else:
        today = date.today()
        dates = [(today + timedelta(days=i)).isoformat() for i in range(args.days)]

    calendar = {}
    for d in dates:
        rows = fetch_day(d)
        hits = [r for r in rows if r.get("symbol") in universe]
        if hits:
            calendar[d] = [{"symbol": r["symbol"], "name": r.get("name", ""),
                            "time": (r.get("time") or "").replace("time-", ""),
                            "eps_forecast": r.get("epsForecast", "-")} for r in hits]
        print(f"  {d}: {len(rows)}只全市场财报，{len(hits)}只命中followed universe")

    out = ROOT / "data" / "cache" / f"earnings_calendar_{date.today():%Y%m%d}.json"
    json.dump({"universe_size": len(universe), "calendar": calendar},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {out}")
    if not calendar:
        print("followed universe本周（或指定日）无财报。")
    for d, hits in calendar.items():
        for h in hits:
            print(f"  {d}  {h['symbol']:6s} {h['time']:12s} EPS预期{h['eps_forecast']}  {h['name']}")


if __name__ == "__main__":
    main()
