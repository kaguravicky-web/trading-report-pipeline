#!/usr/bin/env python3
"""成交对拍：券商成交明细 ↔ tradebook 里记的腿。

起因（2026-08-21）：
  - longbridge 的全量成交查询**会静默漏单**——8/20 ONDS 有一笔 10:01 ET 卖 400@8.40，
    落在查询时间窗内、返回条数也没到上限，就是没返回。逐标的重查才挖出来。
    没有它，ONDS 那 400 股会被算成还持有。
  - moomoo 这边全靠人工把 CSV 读进脚本，转录错一位数没人发现。
所以把「券商说成交了什么」和「tradebook 里记了什么」做成一条可重复跑的对账，
而不是每次靠眼睛看。Vic 定的切换计划：接 moomoo API 后先 CSV+API 并行对拍一两周，
笔笔一致再停 CSV——那时把 API 取到的成交也转成同样的 canonical 格式喂给 diff_fills 即可。

比对粒度是 **(日期, 代码, 方向) → 总股数 + 成交量加权均价**，不是逐笔。
因为 tradebook 允许把同价的多笔成交并成一条腿（例如 MRVL 8股+19股 同价 215.08 记成 27股），
逐笔比会满屏假阳性；总量+加权均价既能抓住漏单/多记/写错价，又不受合并腿影响。

用法：
    python scripts/check_fills.py "路径/历史-保证金账户(5930)-YYYYMMDD-HHMMSS.csv"
    python scripts/check_fills.py <csv> --date 2026-08-20      # 只对某天
不带参数时不做任何事（避免误跑）。退出码非0表示对不上。
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TB_PATH = ROOT / "data" / "tradebook.json"
TOL_QTY = 0          # 股数必须完全一致
TOL_PRICE = 0.005    # 加权均价容差（分位以下的舍入差不算问题）


def _num(s):
    s = (s or "").strip().replace(",", "")
    return float(s) if s else 0.0


def parse_moomoo_csv(path):
    """moomoo「历史-保证金账户」导出 → canonical 成交列表。

    两个坑：
      ①一张订单分多笔成交时，后续行的「方向/代码」是空的，要沿用上一行的（续行）。
      ②「成交时间」才是成交发生的日子，「下单时间」不是——8/17 挂的止损单 8/18 才成交，
        按下单时间归日会把整批平仓记到错误的一天（这个错犯过，见 tradebook 里 WOLF 的日期修正）。
    """
    fills = []
    side = ticker = None
    declared = None      # 当前订单主行声明的 (总成交股数, 成交均价)
    acc = []             # 当前订单已累计的成交行
    bad = []

    def close_order():
        """收尾一张订单：累计的成交行必须等于主行「已成交@均价」声明的量。

        这一步不是多余的：续行（方向/代码为空的那些）靠"沿用上一行"来归属，
        一旦某张单的主行缺失/错位，它的续行会被**静默算到上一张单头上**，
        金额和股数都还是"看起来正常"的。用主行自带的声明值兜一道，孤儿行就藏不住。
        """
        if declared is None:
            return
        dq, dp = declared
        aq = sum(f["qty"] for f in acc)
        if aq != dq:
            bad.append(f"{ticker} 订单声明成交 {dq} 股，明细行加起来是 {aq} 股"
                       f"——CSV 结构对不上（可能有续行错位），解析结果不可信")
        elif aq:
            ap = sum(f["qty"] * f["price"] for f in acc) / aq
            if abs(ap - dp) > 0.01:
                bad.append(f"{ticker} 订单声明均价 {dp}，明细行算出 {ap:.4f}")

    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            d = (row.get("方向") or "").strip()
            t = (row.get("代码") or "").strip()
            if d:                       # 主行：先给上一张单收尾，再开新单
                close_order()
                side, ticker = d, t
                acc = []
                m = (row.get("已成交@均价") or "").strip()   # 形如 "110@67.93182"
                if "@" in m:
                    q, p = m.split("@", 1)
                    declared = (int(_num(q)), _num(p))
                else:
                    declared = None
            qty = _num(row.get("成交数量"))
            price = _num(row.get("成交价格"))
            when = (row.get("成交时间") or "").strip()
            if qty <= 0 or not when or not ticker:
                continue                # 未成交/已撤单/下单失败的行
            if side not in ("买入", "卖出"):
                bad.append(f"未知方向 {side!r}（{ticker} {when}）")
                continue
            date = when.split()[0].replace("/", "-")
            rec = {"date": date, "ticker": ticker,
                   "action": "buy" if side == "买入" else "sell",
                   "qty": int(qty), "price": price}
            fills.append(rec)
            acc.append(rec)
        close_order()

    if bad:
        raise SystemExit("CSV 解析自检未通过，没有继续对拍（先确认导出文件是完整的）：\n  "
                         + "\n  ".join("[!] " + b for b in bad))
    return fills


def tradebook_fills(account, dates):
    store = json.loads(TB_PATH.read_text(encoding="utf-8"))
    out = []
    for t in store.get("trades", []):
        if t.get("account") != account:
            continue
        for l in (t.get("legs") or []):
            if l.get("date") in dates and l.get("qty") and l.get("price") is not None:
                out.append({"date": l["date"], "ticker": t["ticker"], "action": l["action"],
                            "qty": l["qty"], "price": l["price"], "_id": t["id"]})
    return out


def _agg(fills):
    """按 (日期,代码,方向) 汇总成 总股数 + 成交量加权均价。"""
    g = defaultdict(lambda: [0, 0.0])
    for f in fills:
        k = (f["date"], f["ticker"], f["action"])
        g[k][0] += f["qty"]
        g[k][1] += f["qty"] * f["price"]
    return {k: (q, amt / q) for k, (q, amt) in g.items() if q}


def diff_fills(broker, book, label_a="券商", label_b="tradebook"):
    A, B = _agg(broker), _agg(book)
    problems = []
    for k in sorted(set(A) | set(B)):
        date, tk, act = k
        qa, pa = A.get(k, (0, 0.0))
        qb, pb = B.get(k, (0, 0.0))
        if qa and not qb:
            problems.append(f"{date} {tk} {act} {qa}股@{pa:.4f} —— 只有{label_a}有，{label_b}**漏记**")
        elif qb and not qa:
            problems.append(f"{date} {tk} {act} {qb}股@{pb:.4f} —— 只有{label_b}有，{label_a}没有这笔")
        elif abs(qa - qb) > TOL_QTY:
            problems.append(f"{date} {tk} {act} 股数不一致：{label_a} {qa} vs {label_b} {qb}")
        elif abs(pa - pb) > TOL_PRICE:
            problems.append(f"{date} {tk} {act} {qa}股 均价不一致："
                            f"{label_a} {pa:.4f} vs {label_b} {pb:.4f}")
    return problems


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 0
    path = Path(argv[1])
    only = None
    if "--date" in argv:
        only = argv[argv.index("--date") + 1]

    broker = parse_moomoo_csv(path)
    if only:
        broker = [f for f in broker if f["date"] == only]
    if not broker:
        print("CSV 里没有成交记录（或该日期没有），什么都没对。")
        return 1
    dates = sorted({f["date"] for f in broker})
    book = tradebook_fills("moomoo", set(dates))

    print(f"对拍范围：{dates[0]} ~ {dates[-1]}（{len(dates)}天）")
    print(f"  券商成交 {len(broker)} 笔 / tradebook 腿 {len(book)} 条")
    problems = diff_fills(broker, book)
    if problems:
        print(f"\n对不上 {len(problems)} 处：")
        for p in problems:
            print("  [!] " + p)
        return 1
    print("\n逐 (日期·代码·方向) 的总股数与加权均价全部一致 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
