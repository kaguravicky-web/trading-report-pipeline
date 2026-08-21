#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓管理执行表（2026-08-13 建）——教材 p14 的机器化。

**为什么建这个，而不是先接选股扫描器**（2026-08-13 用 51 笔跟单实测出来的）：

    ≥5 分那批（教材七问）：峰值均值 +10.28% → 实际均值 +0.34%
    ≤4 分那批：            峰值均值 +10.57% → 实际均值 -0.50%

    **两组峰值几乎一样——p16 七问对「能涨多少」没有预测力。**
    而 51 笔里曾浮盈 ≥10% 的有 18 笔，其中 **13 笔最终 ≤0% 收场**；
    这 18 笔峰值均值 +22.3% → 实际 -0.2%，**放走 22.4pt**。
    「吃到峰值的百分之几」中位数 **-6%**，45 笔里 34 笔不到 20%。

    **结论：老师的选股是有效的，瓶颈 100% 在持有和退出。**
    所以先做 p14，不做 p16。

教材 p14 原文（本表逐条落地）：
    「第 3–5 日可按規則賣出 1/3 至 1/2，並把餘倉止損移至損益平衡。」
    「餘下倉位選用 EMA10 或 EMA20 跟蹤，選定後保持一致。」
    「以**首次收盤跌破**所選均線作退出參考，不因盤中短暫刺穿而情緒化反應。」
    「不要因為已有浮盈就過早全部賣出；策略需要少數大贏家。」

🔴 跟踪线不是全局选一条，是**每只票按自己的回踩历史定**（见 ema_trail.py，
   Vic 2026-08-13 纠正过我这一点）。选定后写进 tradebook，中途不改。

用法：
    python scripts/position_manage.py
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 🔴 2026-08-17 Vic：「我其实不是硬性3天peel，只是说突破以后延续peel，
#    然后没有Playout我考虑的是止损和减仓」——**天数不再是触发条件**，只作参考显示。
TRIM_DAY_MIN, TRIM_DAY_MAX = 3, 5      # 仅用于「持有第几日」的显示，不再当触发闸门
CONTINUATION_PNL = 3.0                 # 浮盈 ≥ 此值 = 突破后在延续 → 按 peel 分批减
NO_PLAYOUT_DAYS = 3                    # 持有 ≥ 此天数
NO_PLAYOUT_PNL = 1.0                   # 且浮盈 < 此值 = 没走出来 → 考虑止损/减仓


def load_legs():
    """从 tradebook 取每只在场标的的腿：首次买入日、累计买/卖股数。"""
    tb = json.loads((ROOT / "data/tradebook.json").read_text(encoding="utf-8"))
    trades = tb if isinstance(tb, list) else tb.get("trades")
    out = {}
    for t in trades:
        if not isinstance(t, dict) or t.get("status") != "open":
            continue
        legs = [l for l in (t.get("legs") or []) if isinstance(l, dict) and l.get("date")]
        if not legs:
            continue
        legs.sort(key=lambda l: l["date"])
        key = (t.get("ticker"), t.get("account"))
        # 🔴 腿的字段是 action（"buy"/"sell"），不是 side；日期字段是 date，不是 d
        bought = sum(float(l.get("qty") or 0) for l in legs if l.get("action") != "sell")
        # 🔴 2026-08-17：**同日、同价（±0.5%）的卖出是「买重复了」的更正，不是 peel**
        #    （Vic：「now是买重复了」——NOW 当天买 90 卖 45，价差 0.01）。
        #    记成已减仓会让「已减仓但止损未移到成本位」这条误报，也会让 peel 状态失真。
        def _is_dup_correction(sell_leg):
            """同日、同价（±0.5%）买过一笔 → 这次卖出是撤重复单，不是 peel。"""
            return any(b.get("action") != "sell"
                       and str(b.get("date"))[:10] == str(sell_leg.get("date"))[:10]
                       and b.get("price") and sell_leg.get("price")
                       and abs(b["price"] / sell_leg["price"] - 1) <= 0.005
                       for b in legs)

        all_sells = [l for l in legs if l.get("action") == "sell"]
        real_sells = [l for l in all_sells if not _is_dup_correction(l)]
        sold = sum(float(l.get("qty") or 0) for l in real_sells)
        dup_corrected = len(real_sells) < len(all_sells)
        out[key] = {
            "first": legs[0]["date"][:10], "n_legs": len(legs),
            "bought": bought, "sold": sold,
            "mentor": bool(t.get("mentor")), "setup": t.get("setup_type"),
            "dup_corrected": dup_corrected,
            "trail": t.get("trail_ema"),          # 选定后写回 tradebook 的字段
        }
    return out


def main():
    import report_helpers as H
    import fetch_market_data as F
    import ema_trail as ET
    from longport.openapi import QuoteContext, Config

    pos = H.load_tradebook_positions()
    legs = load_legs()
    ctx = QuoteContext(Config.from_apikey_env())

    rows, data_date = [], None
    for p in pos:
        tk, acct = p["ticker"], p["account"]
        info = legs.get((tk, acct)) or legs.get((tk, None)) or {}
        try:
            bars = F.fetch_bars(ctx, tk, 130)
        except Exception:
            continue
        if not bars:
            continue
        px = bars[-1]["c"]
        data_date = max(data_date or "", bars[-1]["date"])
        cost, stop = p.get("cost"), p.get("stop")
        if not stop:                 # 🔴 tradebook 里「无止损」写的是 0，不是 null
            stop = None
        pnl = (px / cost - 1) * 100 if cost else None

        # 持仓交易日数：**买入当天算第 1 日**（教材「第 3–5 日」是从进场那天数起）
        first = info.get("first")
        days = sum(1 for b in bars if b["date"] >= first) if first else None

        # 跟踪线：tradebook 里选定过就用选定的，否则用 ema_trail 的建议
        et = ET.analyze(tk, bars)
        pick = info.get("trail") or (et["pick"] if et else None)
        line = None
        if et:
            line = et["ema10"] if pick == "EMA10" else et["ema20"]
        dist = (px / line - 1) * 100 if line else None

        trimmed = (info.get("sold") or 0) > 0
        # 🔴 2026-08-17 Vic：「止损=成本? 应该改成 止损>成本」——
        # 止损**等于**成本不算已保护：手续费和滑点会把它吃成小亏。
        be = (stop is not None and cost is not None and stop > cost)

        # ---- 动作判定（2026-08-17 按 Vic 的实际做法重写）----
        # 旧版按「第 3-5 日」当硬闸门触发减仓。Vic：「我其实不是硬性3天peel，
        # 只是说突破以后延续peel，然后没有Playout我考虑的是止损和减仓」。
        # 所以触发条件改成**走势状态**，天数只作参考显示。
        act = []
        if line and px < line:
            act.append(f"🔴**收盘已跌破{pick} {line:.2f}** → 退出（不等盘中）")
        if info.get("dup_corrected"):
            act.append("ℹ️同日同价的卖出已识别为**买重复了的更正**，不计入减仓")

        if pnl is not None and pnl >= CONTINUATION_PNL:
            tag = "已减过，继续按延续分批" if trimmed else "**突破后在延续 → 按 peel 分批减**"
            act.append(f"🎯浮盈 {pnl:+.1f}%（第 {days} 日）→ {tag}")
        elif H.is_basket(tk):
            # 🔴 2026-08-18 Vic：「SOXX 算指数吧」——**第②条不适用于篮子仓**。
            #    ②「没有 playout」问的是「突破走出来没有」，那是 setup 交易的判据；
            #    篮子仓买的是一层暴露（半导体/纳指），进场理由本来就不是形态走出来。
            #    8/17 我拿②去判 SOXX，得出「你加仓和规则冲突」——**是我用错了尺子**。
            act.append(f"篮子仓（ETF）：第 {days} 日、浮盈 {pnl:+.1f}%。"
                       f"**②「没有 playout」不适用**——它买的是一层暴露不是一个形态。"
                       f"仍按①延续 peel / ③止损高于成本 / ④收盘破跟踪线才出")
        elif days is not None and days >= NO_PLAYOUT_DAYS and (pnl is None or pnl < NO_PLAYOUT_PNL):
            act.append(f"🔴**没有 playout**：第 {days} 日、浮盈仅 {pnl:+.1f}% → "
                       f"**考虑止损或减仓**，不要等它自己走出来")
        elif days is not None and days < NO_PLAYOUT_DAYS:
            act.append(f"持有第 {days} 日，等它走出来")
        else:
            act.append(f"第 {days} 日、浮盈 {pnl:+.1f}%，在延续和没走出来之间")

        if stop is None:
            # 篮子仓无止损是配置选择（QQQ 2026-08-04 Vic 确认），不标红
            act.append("篮子仓 · 无止损（有意为之）" if H.is_basket(tk) else "🔴**无止损**")
        elif trimmed and not be:
            act.append(f"🔴**已减仓但止损未高于成本**（止损 {stop} vs 成本 {cost:.2f}）")
        if not line:
            act.append("（历史不足 70 根，算不出跟踪线）")
        rows.append({
            "ticker": tk, "acct": acct, "days": days, "pnl": pnl,
            "trimmed": trimmed, "be": be, "stop": stop, "cost": cost, "px": px,
            "pick": pick, "line": line, "dist": dist,
            "mentor": info.get("mentor"), "act": "；".join(act) or "持有，无动作",
        })

    rows.sort(key=lambda r: (r["days"] is None, -(r["days"] or 0)))
    # 🔴 落盘戳的是**最后一根 K 的日期**，不是 today()——盘后报告用 data_date 校验口径日，
    #    跟 CONTEXT.md「任何价格必须来自口径日的 cache」同一条纪律。SGT 白天跑时
    #    today() 会比数据日期快一天，用它做校验会天天误报。
    cache = ROOT / "data/cache/position_manage.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"data_date": data_date, "run_at": str(date.today()),
                                 "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n持仓管理执行表 · 数据日 {data_date}  （教材 p14）")
    print(f"{'TICKER':<7}{'账户':<12}{'持仓日':<7}{'浮盈':<9}{'减过?':<7}{'止损>成本?':<11}"
          f"{'跟踪线':<8}{'线位':<10}{'距线':<9}今日动作")
    for r in rows:
        pnl_s = f"{r['pnl']:+.1f}%" if r["pnl"] is not None else "-"
        line_s = f"{r['line']:.2f}" if r["line"] else "-"
        dist_s = f"{r['dist']:+.1f}%" if r["dist"] is not None else "-"
        trim_s = "是" if r["trimmed"] else "否"
        be_s = "是" if r["be"] else "否"
        tk_s = r["ticker"] + ("*" if r["mentor"] else "")
        print(f"{tk_s:<7}{r['acct']:<12}{str(r['days'] or '-'):<7}{pnl_s:<9}"
              f"{trim_s:<7}{be_s:<11}{r['pick'] or '-':<8}{line_s:<10}{dist_s:<9}{r['act']}")

    print("\n* = mentor 跟单（减仓/退出听老师的，本表只做记账和提醒，不替他下结论）")
    print("🔴 触发口径（2026-08-17 按 Vic 的实际做法改，**天数不再是闸门**）：")
    print("   ①**突破后在延续**（浮盈 ≥3%）→ 按 peel 分批减")
    print("   ②**没有 playout**（持有 ≥3 日但浮盈 <1%）→ 考虑止损或减仓，不等它自己走出来")
    print("      **② 不适用于篮子仓**（ETF，名单见 report_helpers.BASKET_POSITIONS）——"
          "它买的是一层暴露不是一个形态（2026-08-18 Vic）")
    print("   ③余仓止损要**高于**成本（等于成本不算已保护，手续费和滑点会吃掉）")
    print("   ④余仓按选定 EMA 跟踪，**首次收盘**跌破才出，不看盘中")
    print("🔴 51 笔跟单实测：曾浮盈 ≥10% 的 18 笔里 13 笔最终 ≤0% 收场，"
          "平均放走 22.4pt——**这张表就是为了堵这个洞**")
    return rows


if __name__ == "__main__":
    main()
