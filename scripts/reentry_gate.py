#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重入闸门（2026-07-23建，解决Vic："我经常这样挨刀，突破交易总是踩这样的坑"）。

**要解决的具体模式：** 止损离场 → 价格回到原来的位置 → 重新买入 → 再挨一刀。
台账实证：XSW 7/17卖177.27、7/22买177.26（价差-0.01%）；SHOP 7/15卖122.72、7/22买122.40（-0.26%）。
隔了5-7天，价格回到原点就买回来，中间没有任何结构性变化——止损这个动作等于白做，
只付了手续费和滑点，然后重新站回同一个位置等第二刀。

**闸门的核心判据：重入必须有"第一次入场时不存在的新信息"。** 光是"跌够了"/"回到原价了"
/"看起来企稳了"都不算——那些在第一次入场时你也是这么想的。

三道闸（任一不过即禁止重入）：
  闸1·同价禁令   —— 现价在上次卖出价的±2%以内 且 距上次卖出<5个交易日 → 禁止
  闸2·新结构     —— 必须满足下列之一（都是第一次入场时不存在的事实）：
                     a) 新洗盘低点：期间创出低于上次止损位的新低，且已收回到止损位上方
                     b) 放量确认：出现量比≥1.5×且收盘位置>60%的阳线
                     c) 突破新高：收盘站上上次失败突破位之上（不是回到，是站上）
  闸3·冷却期     —— 距上次卖出至少3个交易日（对应"0天持有胜率仅8%"那条实证）

**这个脚本只做机械核对，不替你做决定。** "板块是否已经轮动到位"这一条是判断题，
脚本给不出答案，需要你自己看盘前报告的板块RS表。

用法：
    python scripts/reentry_gate.py XSW              # 查单只
    python scripts/reentry_gate.py XSW SHOP CRWD    # 批量
    python scripts/reentry_gate.py --all            # 扫描tradebook里全部平仓过的标的
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SAME_PRICE_PCT = 2.0      # 闸1：±2%算"同价"
SAME_PRICE_DAYS = 5       # 闸1：5个交易日内
COOLDOWN_DAYS = 3         # 闸3：冷却期
VOL_BURST = 1.5           # 闸2b：放量倍数
RANGE_POS_MIN = 60        # 闸2b：收盘位置%


def load_exits():
    """从tradebook取每只票最近一次的平仓记录（日期+价格+止损位）。"""
    tb = json.loads((ROOT / "data" / "tradebook.json").read_text(encoding="utf-8"))
    out = {}
    for t in tb.get("trades", []):
        tk = t.get("ticker")
        if not tk or t.get("status") != "closed":
            continue
        legs = [l for l in (t.get("legs") or []) if l.get("price") and l.get("date")]
        if len(legs) < 2:
            continue
        stops = t.get("stop_history") or []
        rec = {"exit_date": legs[-1]["date"], "exit_px": float(legs[-1]["price"]),
               "entry_px": float(legs[0]["price"]),
               "stop": float(stops[-1]["stop"]) if stops and stops[-1].get("stop") else None,
               "setup": t.get("setup_type"), "mentor": bool(t.get("mentor"))}
        # 只保留最近一次
        if tk not in out or rec["exit_date"] > out[tk]["exit_date"]:
            out[tk] = rec
    return out


def trading_days_between(d1: str, d2: str) -> int:
    """粗略交易日差（跳过周末，不处理节假日——够用，不要为此引入日历依赖）。"""
    a, b = datetime.fromisoformat(d1).date(), datetime.fromisoformat(d2).date()
    if b < a:
        a, b = b, a
    n, cur = 0, a
    while cur < b:
        cur = date.fromordinal(cur.toordinal() + 1)
        if cur.weekday() < 5:
            n += 1
    return n


def check(ticker: str, exits: dict, ctx) -> dict:
    import fetch_market_data as F
    r = {"ticker": ticker, "verdict": None, "reasons": [], "gates": {}}
    ex = exits.get(ticker)
    if not ex:
        r["verdict"] = "N/A"
        r["reasons"].append("tradebook里没有这只票的平仓记录——不属于'重入'，按普通新仓的规则走")
        return r

    bars = F.fetch_bars(ctx, ticker, 40)
    if not bars:
        r["verdict"] = "?"
        r["reasons"].append("拉不到K线数据")
        return r

    today = bars[-1]["date"]
    cur_px = bars[-1]["c"]
    days = trading_days_between(ex["exit_date"], today)
    px_gap = (cur_px / ex["exit_px"] - 1) * 100

    r["info"] = {"上次卖出": f"{ex['exit_date']} @{ex['exit_px']:.2f}",
                 "上次止损位": ex["stop"], "上次setup": ex["setup"],
                 "现价": f"{cur_px:.2f}", "距上次卖出": f"{days}个交易日",
                 "价差": f"{px_gap:+.2f}%"}

    # 闸1：同价禁令
    g1 = not (abs(px_gap) <= SAME_PRICE_PCT and days < SAME_PRICE_DAYS)
    r["gates"]["闸1·同价禁令"] = g1
    if not g1:
        r["reasons"].append(
            f"🔴闸1不过：现价距上次卖出价仅{px_gap:+.2f}%（阈值±{SAME_PRICE_PCT}%），"
            f"且只隔了{days}个交易日（阈值{SAME_PRICE_DAYS}天）——这就是XSW/SHOP那个模式，"
            f"价格回到原点不等于结构修复")

    # 闸2：新结构（三选一）
    since = [b for b in bars if b["date"] > ex["exit_date"]]
    sub_a = sub_b = sub_c = False
    if since and ex["stop"]:
        lows = [b["l"] for b in since]
        if min(lows) < ex["stop"] and cur_px > ex["stop"]:
            sub_a = True
            r["reasons"].append(
                f"✅闸2a：期间创出新低{min(lows):.2f}（低于上次止损{ex['stop']:.2f}）且现价已收回其上"
                f"——这是一个第一次入场时不存在的新洗盘低点")
    if len(bars) >= 21:
        vol20 = sum(b["v"] for b in bars[-21:-1]) / 20
        for b in since:
            h, l, c = b["h"], b["l"], b["c"]
            rp = (c - l) / (h - l) * 100 if h > l else 0
            if vol20 and b["v"] / vol20 >= VOL_BURST and rp > RANGE_POS_MIN and c > b["o"]:
                sub_b = True
                r["reasons"].append(
                    f"✅闸2b：{b['date']}出现放量确认阳线（量比{b['v']/vol20:.2f}×、收盘位置{rp:.0f}%）")
                break
    if since:
        prior_high = max(b["h"] for b in bars[:len(bars) - len(since)][-20:])
        if cur_px > prior_high:
            sub_c = True
            r["reasons"].append(f"✅闸2c：现价{cur_px:.2f}已站上离场前20日高点{prior_high:.2f}")
    g2 = sub_a or sub_b or sub_c
    r["gates"]["闸2·新结构"] = g2
    if not g2:
        r["reasons"].append(
            "🔴闸2不过：离场之后没有出现任何新结构（无新洗盘低点+收回 / 无放量确认阳线 / 未站上前高）"
            "——重入的理由跟第一次入场是同一个，止损等于白做")

    # 闸3：冷却期
    g3 = days >= COOLDOWN_DAYS
    r["gates"]["闸3·冷却期"] = g3
    if not g3:
        r["reasons"].append(
            f"🔴闸3不过：距上次卖出仅{days}个交易日（需≥{COOLDOWN_DAYS}）"
            f"——实证：0天持有的交易胜率仅8%，是全部持有时长分桶里最差的")

    r["verdict"] = "允许评估" if (g1 and g2 and g3) else "禁止重入"
    if r["verdict"] == "允许评估":
        r["reasons"].append(
            "⚠️三道闸都过了，但这只是'可以开始评估'不是'可以买'——"
            "板块是否已轮动到位、setup本身干不干净，仍要看盘前报告和你自己的图")
    return r


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    exits = load_exits()
    if "--all" in sys.argv:
        args = sorted(exits.keys())
    if not args:
        print(__doc__)
        print("tradebook里有平仓记录的标的：", ", ".join(sorted(exits.keys())))
        return

    from longport.openapi import QuoteContext, Config
    ctx = QuoteContext(Config.from_apikey_env())

    for tk in args:
        r = check(tk, exits, ctx)
        print(f"\n{'='*70}\n{tk}  →  【{r['verdict']}】")
        if r.get("info"):
            for k, v in r["info"].items():
                print(f"  {k}: {v}")
        if r.get("gates"):
            print("  " + "  ".join(f"{k}={'✅' if v else '🔴'}" for k, v in r["gates"].items()))
        for x in r["reasons"]:
            print(f"  {x}")


if __name__ == "__main__":
    main()
