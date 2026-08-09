#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""半导体超跌反弹观察池扫描（2026-07-21新建，Vic："应该看半导体的超跌反弹了，market leaders加回去，
RSI跌到30以下，开始观测"）。ML Market Leader名单重新启用，但性质从"相对强势领袖"改成
"绝对超跌观察池"——扫描半导体/AI硬件相关标的的RSI14，RSI<25即进入观察（25-30算预备观察）。
2026-07-28 Vic："RSI<30筛池方向 改成25试试"——30这一档已三次被证明方向是反的
（真正被打的是RSI 38-42那批：NVDA 42.4 -4.99%、ASML 41.1 -5.80%、SNDK 38.3 -11.02%，
而池里的KLAC 26.3 / GFS 29.0反而抗跌）。先收紧阈值观察，不直接换指标。
不是跑一次就固定名单，每次盘前/盘后都要重新跑，池子随RSI滚动增减。见CONTEXT.md「ML Market
Leader名单」章节完整规则。

用法：
    python scripts/scan_semis_rsi.py
输出：data/cache/semis_scan_YYYYMMDD.json + 终端按RSI升序打印全量+RSI<30名单
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_market_data as F

# 旧ML_LEADERS 14只 + 主流半导体/设备/封测/模拟链，覆盖面比原名单宽，因为筛选逻辑现在是"谁跌破30"
# 不是"谁是领袖"，候选池本身要够大才能不漏掉新跌破的标的
SEMIS_UNIVERSE = list(dict.fromkeys(F.ML_LEADERS + [
    "NVDA", "AMD", "AVGO", "TSM", "QCOM", "LRCX", "KLAC", "AMAT", "ASML", "ON", "MPWR", "TER", "SWKS",
    "WOLF", "MXL", "COHR", "LITE", "ALAB", "ARM", "AAOI", "WDC", "MRAM", "AEHR", "POWI", "VECO", "ONTO",
    "TSEM", "AXTI", "AMKR", "GFS", "SITM", "MTSI", "DIOD", "SYNA", "VSH",
]))


def main():
    from longport.openapi import QuoteContext, Config
    ctx = QuoteContext(Config.from_apikey_env())

    out = {}
    skipped = []
    for t in SEMIS_UNIVERSE:
        bars = F.fetch_bars(ctx, t, F.BARS_NEEDED)
        if not bars:
            skipped.append(t)
            continue
        out[t] = F.analyze(bars)

    cache_dir = ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"semis_scan_{date.today().strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    rows = sorted(
        ((t, m.get("rsi14"), m.get("t1_pct"), m.get("d5_pct"), m.get("d21_pct"),
          m.get("off_52w_high_pct"), m.get("range_pos"), m.get("dist_ma50_atr"))
         for t, m in out.items()),
        key=lambda r: (r[1] if r[1] is not None else 999),
    )
    print(f"{'TICKER':8}{'RSI14':>8}{'T-1%':>8}{'5d%':>8}{'21d%':>8}{'off52w%':>10}{'rangePos':>10}{'dist50ATR':>11}")
    for r in rows:
        print(f"{r[0]:8}{r[1]:>8.1f}{r[2]:>8.2f}{r[3]:>8.2f}{r[4]:>8.2f}{r[5]:>10.2f}{r[6]:>10}{r[7]:>11.2f}")
    print("wrote", out_path)
    if skipped:
        print("skipped:", skipped)
    below30 = [r[0] for r in rows if r[1] is not None and r[1] < 25]
    approaching = [r[0] for r in rows if r[1] is not None and 25 <= r[1] < 30]
    print("\nRSI<30 (确认观察):", below30)
    print("RSI 25-30 (预备观察):", approaching)


if __name__ == "__main__":
    main()
