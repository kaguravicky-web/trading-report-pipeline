#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""省token版实时报价（2026-07-12建）——替代交互式MCP quote-realtime-info调用。

MCP的quote-realtime-info每只票返回一整坨嵌套JSON（pre/post market各自一份，加起来
5-800 token/只），查10来只就是几千token堆进对话。这里用SDK直连，只吐一行需要的数字，
10只票的输出比MCP查1只票还省。

用法：
    python scripts/quick_quote.py SPY QQQ SMH
    python scripts/quick_quote.py ARKK RDDT --premarket   # 盘前时段，顺带算盘前%
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from longport.openapi import QuoteContext, Config


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_pm = "--premarket" in sys.argv
    if not args:
        print("用法: python quick_quote.py TICKER [TICKER...] [--premarket]")
        return
    symbols = [a.upper() + (".US" if "." not in a else "") for a in args]
    ctx = QuoteContext(Config.from_apikey_env())
    for q in ctx.quote(symbols):
        tk = q.symbol.replace(".US", "")
        last = float(q.last_done)
        prev = float(q.prev_close) if getattr(q, "prev_close", None) else None
        pct = (last / prev - 1) * 100 if prev else None
        line = f"{tk:6s} {last:>10.3f}"
        if pct is not None:
            line += f"  {pct:+.2f}%"
        if show_pm:
            pm = getattr(q, "pre_market_quote", None)
            if pm and float(pm.last_done or 0) > 0:
                pm_px = float(pm.last_done)
                pm_pct = (pm_px / last - 1) * 100 if last else None
                line += f"  | 盘前{pm_px:.2f}({pm_pct:+.2f}%)" if pm_pct is not None else f"  | 盘前{pm_px:.2f}"
        print(line)


if __name__ == "__main__":
    main()
