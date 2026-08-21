#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""止盈影子台账（2026-08-20 建）。

🔴 **为什么要「影子」**：Vic 原话「但是其实我不一定会跟你，你单独做你的回测」。
   所以这个台账**完全不依赖他有没有照做**：它只读 tradebook 的建仓事实
   （哪只票、哪天进、成本多少、初始止损多少），然后按规则自己走一遍，
   得出「规则会怎么做」；他实际怎么做另算一列。两边每周对一次。

   **这是这个模块唯一正确的形态。**如果台账只在他照做时才记录，
   那记的就是「他照做的那些天」，样本自带选择偏差——
   跟 8/17 那次「用自提及至今算账号强弱」是同一个错误
   （见 CONTEXT「X trader 台账」那节的教训）。

规则（2026-08-20 回测选出，见 reference/take_profit_backtest_20260820.md）：
    **浮盈 ≥ 0.6 × ADR20 的那天收盘，全部卖出。**
  · ADR20 取**建仓日之前** 20 根日K的平均振幅，无未来函数
  · 硬止损用账本的 stop_initial，盘中触及即出
  · 回测结论：47 笔隔夜仓上 +12.0R vs 实际 +5.9R，且 0 笔悬空
  · ⚠️ **已知代价**：≥2R 的笔数会从 2 压到 1。样本只有两个月、且都是冲高转折的行情，
    对移动止损最不利、对止盈最有利——**这是一个待证伪的假设，不是定论。**

用法：
    python scripts/tp_shadow.py --update     # 刷新台账（每天盘前/盘后跑）
    python scripts/tp_shadow.py --report     # 打印规则 vs 实际
    python scripts/tp_shadow.py --week       # 本周复盘（周报用）
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

TP_MULT = 0.6
LEDGER = ROOT / "data" / "tp_shadow.json"


def _bars(ctx, tk, n=250):
    from longport.openapi import Period, AdjustType
    try:
        b = ctx.candlesticks(tk + ".US", Period.Day, n, AdjustType.NoAdjust)
        return [{"d": str(x.timestamp)[:10], "h": float(str(x.high)),
                 "l": float(str(x.low)), "c": float(str(x.close))} for x in b]
    except Exception:
        return []


def adr20(bars, day):
    bs = [b for b in bars if b["d"] < day][-20:]
    if len(bs) < 10:
        return None
    return sum((b["h"] - b["l"]) / b["c"] for b in bs) / len(bs)


def build(update=True):
    tb = json.loads((ROOT / "data" / "tradebook.json").read_text(encoding="utf-8"))
    from longport.openapi import QuoteContext, Config
    ctx = QuoteContext(Config.from_apikey_env())

    cache = {}
    out = []
    for t in tb["trades"]:
        legs = t.get("legs") or []
        buys = [x for x in legs if x["action"] == "buy"]
        if not buys:
            continue
        if t.get("entry_date") == t.get("exit_date"):
            continue                                  # 日内单不进（规则管的是隔夜仓）
        tk, d0 = t["ticker"], t["entry_date"]
        if not d0:
            continue
        if tk not in cache:
            cache[tk] = _bars(ctx, tk)
        bars = cache[tk]
        if not bars:
            continue
        adr = adr20(bars, d0)
        if not adr:
            continue
        q = sum(x["qty"] for x in buys)
        cost = sum(x["qty"] * x["price"] for x in buys) / q
        stop = t.get("stop_initial")
        risk = (cost - stop) if (stop and cost > stop) else None
        tp_px = cost * (1 + TP_MULT * adr)

        # 规则走一遍
        hit_d = hit_p = None
        stopped = False
        for b in bars:
            if b["d"] < d0:
                continue
            if stop and b["l"] <= stop:
                stopped = True
                break
            if b["c"] >= tp_px:
                hit_d, hit_p = b["d"], b["c"]
                break

        sells = [x for x in legs if x["action"] == "sell"]
        act_d = t.get("exit_date")
        act_p = (sum(x["qty"] * x["price"] for x in sells) /
                 sum(x["qty"] for x in sells)) if sells else None

        rule_px = stop if stopped else (hit_p if hit_p else None)
        row = {
            "ticker": tk, "account": t.get("account"), "entry_date": d0,
            "cost": round(cost, 4), "stop": stop, "adr20_pct": round(adr * 100, 2),
            "tp_price": round(tp_px, 4),
            "rule_exit_date": (d0 if stopped else hit_d),
            "rule_exit_price": round(rule_px, 4) if rule_px else None,
            "rule_state": ("止损出" if stopped else ("已止盈" if hit_d else "持有中")),
            "actual_exit_date": act_d, "actual_exit_price": round(act_p, 4) if act_p else None,
            "actual_state": t.get("status"),
        }
        if risk:
            row["risk"] = round(risk, 4)
            if rule_px:
                row["rule_R"] = round((rule_px - cost) / risk, 3)
            if act_p:
                row["actual_R"] = round((act_p - cost) / risk, 3)
        out.append(row)

    doc = {
        "_说明": [
            "止盈影子台账：**不依赖 Vic 有没有照做**，只按 tradebook 的建仓事实自己走规则。",
            "Vic 2026-08-20：「但是其实我不一定会跟你，你单独做你的回测」。",
            "规则 = 浮盈 ≥ %.1f × ADR20 的那天收盘全出；硬止损用 stop_initial 盘中触及即出。" % TP_MULT,
            "回测出处：reference/take_profit_backtest_20260820.md",
            "⚠️ 已知代价：≥2R 的笔数会被压低。样本只有两个月且都是冲高转折行情——**待证伪，不是定论**。",
        ],
        "rule": {"tp_mult": TP_MULT, "basis": "ADR20（建仓日之前 20 根）",
                 "action": "全出", "started": "2026-08-20"},
        "generated_at": date.today().isoformat(),
        "positions": out,
    }
    if update:
        LEDGER.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def report(doc, since=None):
    ps = [p for p in doc["positions"] if not since or (p["entry_date"] >= since)]
    done = [p for p in ps if p.get("rule_R") is not None and p.get("actual_R") is not None]
    title = "止盈影子台账 · %s" % (("自 %s 起" % since) if since else "全历史")
    print("=" * 78)
    print(title)
    print("=" * 78)
    print("规则：浮盈 ≥ %.1f×ADR20 当天收盘全出（%s）" % (TP_MULT, doc["rule"]["started"]))
    print("样本 %d 笔，其中规则和实际都已出场、可比的 %d 笔" % (len(ps), len(done)))
    if not done:
        print("（还没有可比样本）")
        return
    rr = sum(p["rule_R"] for p in done)
    ar = sum(p["actual_R"] for p in done)
    better = sum(1 for p in done if p["rule_R"] > p["actual_R"])
    print()
    print("  %-16s %+8.1f R   平均 %+.2f R" % ("规则", rr, rr / len(done)))
    print("  %-16s %+8.1f R   平均 %+.2f R" % ("实际", ar, ar / len(done)))
    print("  %-16s %+8.1f R" % ("差额", rr - ar))
    print("  规则更好 %d 笔 / 规则更差 %d 笔" % (better, len(done) - better))
    print("  ≥2R：规则 %d 笔，实际 %d 笔  ← **这是止盈的代价，要盯**"
          % (sum(1 for p in done if p["rule_R"] >= 2),
             sum(1 for p in done if p["actual_R"] >= 2)))
    gap = sorted(done, key=lambda p: (p["rule_R"] - p["actual_R"]))
    print()
    print("  规则吃亏最多的 3 笔（说明止盈砍早了）：")
    for p in gap[:3]:
        print("    %-6s %s  规则 %+.2fR  实际 %+.2fR" %
              (p["ticker"], p["entry_date"], p["rule_R"], p["actual_R"]))
    print("  规则占便宜最多的 3 笔：")
    for p in gap[-3:][::-1]:
        print("    %-6s %s  规则 %+.2fR  实际 %+.2fR" %
              (p["ticker"], p["entry_date"], p["rule_R"], p["actual_R"]))
    holding = [p for p in ps if p["rule_state"] == "持有中"]
    if holding:
        print()
        print("  规则下仍持有 %d 笔（未兑现，不计入上面的对比）：%s"
              % (len(holding), "、".join(p["ticker"] for p in holding[:8])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--week", action="store_true")
    a = ap.parse_args()
    doc = build(update=a.update or not LEDGER.exists())
    if not (a.report or a.week) and a.update:
        print("wrote %s（%d 笔）" % (LEDGER, len(doc["positions"])))
        return
    if a.week:
        since = (date.today() - timedelta(days=7)).isoformat()
        report(doc, since=since)
        print()
    report(doc)


if __name__ == "__main__":
    main()
