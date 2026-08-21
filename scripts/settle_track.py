#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 级候选 D+5 结算（2026-08-20 建）。

Vic：「自入场不需要哦，第五天结算就好了，tradebook 里面和盘后报告拉一次一起结算」
     「结算把它做成一个命令」

🔴 **为什么要做成一个命令**：在此之前结算是散的——
   `setup_a_track_rows` 吐出 `due`，然后要人工判 verdict、再调 `close_setup_track_entries`。
   三步散在盘后 assemble 里，**漏掉任何一步，候选就永远挂在「待评定」**，
   而报告照样渲染得出来（跟 8/12 那条 `ticker="无"` 挂了 5 天是同一个失败模式）。
   现在一条命令跑完：**取价 → 判定 → 写回台账 → 顺带把同名的 tradebook 实盘结果拉出来对照**。

判定口径（写死，不每次重新发明）：
  · 收在 target 之上            → hit
  · 收在 invalid 之下           → miss（止损位被打掉）
  · 5 日累计 ≥ +2%              → hit
  · 5 日累计 ≤ −2%              → miss
  · 其余                        → partial
🔴 **同时拉 tradebook**：候选表记的是「规则说该怎么样」，tradebook 记的是「他实际做了什么」。
   两边并排才看得出**「候选对但没做」和「候选错」是两回事**。

用法：
    python scripts/settle_track.py            # 只看，不写
    python scripts/settle_track.py --commit   # 写回 setup_track.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
import report_helpers as H  # noqa: E402

HIT_PCT, MISS_PCT = 2.0, -2.0


# 🔴 不要在这里另写解析器：2026-08-20 第一版自己写了个 `_num`（取最后一个小数），
#    把 IOT 的失效位从 38.10 抠成了 2.91（句尾是「max(0.5ATR,1%)=2.91%」）。
#    **两个解析器必然漂移**，统一走 H.parse_price_from_text。
_num = H.parse_price_from_text


def tradebook_outcome(ticker, since):
    """同名标的在 tradebook 里的实盘结果——候选表之外的第二个视角。"""
    try:
        tb = json.loads((ROOT / "data" / "tradebook.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    for t in tb.get("trades", []):
        if t.get("ticker") != ticker or (t.get("entry_date") or "") < since:
            continue
        legs = t.get("legs") or []
        buys = [x for x in legs if x["action"] == "buy"]
        sells = [x for x in legs if x["action"] == "sell"]
        if not buys:
            continue
        q = sum(x["qty"] for x in buys)
        cost = sum(x["qty"] * x["price"] for x in buys) / q
        if sells:
            sq = sum(x["qty"] for x in sells)
            ex = sum(x["qty"] * x["price"] for x in sells) / sq
            return {"状态": t.get("status"), "成本": round(cost, 2),
                    "均卖": round(ex, 2), "实盘%": round((ex / cost - 1) * 100, 2)}
        return {"状态": "持有中", "成本": round(cost, 2), "均卖": None, "实盘%": None}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="写回 setup_track.json")
    ap.add_argument("--cache", default=None, help="cache 后缀，默认取最新")
    a = ap.parse_args()

    key = a.cache
    if not key:
        cands = sorted((ROOT / "data" / "cache").glob("market_*.json"))
        key = cands[-1].stem.replace("market_", "")
    cache = H.load_cache(key)
    asof = cache.get("data_date")
    extra = H.track_prices(cache)
    _rows, due = H.setup_a_track_rows(cache, extra)

    print("=" * 92)
    print("A 级候选 D+%d 结算 · 口径日 %s" % (H.SETUP_TRACK_WINDOW, asof))
    print("=" * 92)
    if not due:
        print("今天没有到期的候选（满 %d 个交易日才结算）。" % H.SETUP_TRACK_WINDOW)
        return

    ledger = json.loads((ROOT / "data" / "setup_track.json").read_text(encoding="utf-8"))
    by_key = {(e["date"], e["ticker"]): e for e in ledger["entries"]}
    verdicts = {}
    print("%-11s %-6s %9s %9s %9s %8s %-7s %s"
          % ("信号日", "TICKER", "入场", "失效", "现价", "5日%", "判定", "tradebook 实盘"))
    for d in due:
        e = by_key.get((d["date"], d["ticker"])) or {}
        cur = (cache["metrics"].get(d["ticker"]) or {}).get("close") or extra.get(d["ticker"])
        ep = _num(e.get("entry"), near=cur)
        inv = _num(e.get("invalid"), near=cur)
        tgt = _num(e.get("target"), near=cur)
        pct = d.get("pct_since_signal")
        if cur is not None and inv is not None and cur < inv:
            v = "miss"
        elif cur is not None and tgt is not None and cur >= tgt:
            v = "hit"
        elif pct is not None and pct >= HIT_PCT:
            v = "hit"
        elif pct is not None and pct <= MISS_PCT:
            v = "miss"
        else:
            v = "partial"
        verdicts[(d["date"], d["ticker"])] = v
        tb = tradebook_outcome(d["ticker"], d["date"])
        tb_s = "—" if not tb else "%s 实盘 %s%%" % (tb["状态"], tb["实盘%"] if tb["实盘%"] is not None else "持有中")
        print("%-11s %-6s %9s %9s %9s %8s %-7s %s"
              % (d["date"], d["ticker"],
                 "-" if ep is None else "%.2f" % ep,
                 "-" if inv is None else "%.2f" % inv,
                 "-" if cur is None else "%.2f" % cur,
                 "-" if pct is None else "%+.2f%%" % pct, v, tb_s))

    n = {"hit": 0, "partial": 0, "miss": 0}
    for v in verdicts.values():
        n[v] += 1
    print("-" * 92)
    print("合计 %d 条：命中 %d / 部分 %d / 失误 %d" % (len(verdicts), n["hit"], n["partial"], n["miss"]))
    if a.commit:
        H.close_setup_track_entries(verdicts)
        print("✅ 已写回 data/setup_track.json（status=closed）")
    else:
        print("（只看模式。确认无误后加 --commit 写回）")


if __name__ == "__main__":
    main()
