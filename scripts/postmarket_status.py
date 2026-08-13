#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘后开工体检表（2026-08-11 建，回答 Vic 的「这次不会丢了吗」）。

**盘后会话开工第一件事跑这个。**

为什么必须有它：盘前模板 2026-08-10 失效有三个机械原因，其中最关键的一条是
**「`premarket_status.py`（模板自己写着"每段开工先跑"）一个字都没提模板」**——
文档写得再清楚，新会话不读到就等于没有。盘后一开始连这样一个入口都没有，
所以这个脚本的第一职责不是体检，是**在会话开工的那一秒把模板摆在眼前**。

一屏之内回答：
  ①口径日的 cache 在不在、data_date 对不对（价格必须来自口径日，2026-08-09 定）
  ②三个前置脚本跑了没（fetch_market_data / fetch_earnings_calendar --date / scan_semis_rsi）
  ③当天盘前 JSON 在不在、recon_ledger 有几条（盘后要逐条对，plan/prob 机械复制不许改）
  ④Setup A 台账：盘前B 有没有漏跑 sync、今天有没有满窗待评定
  ⑤tradebook 持仓数 + 当天有没有成交腿（没有 ≠ 没交易，只是提醒你确认）

用法：
    python scripts/postmarket_status.py               # 猜口径日（上一个美股交易日）
    python scripts/postmarket_status.py 2026-08-10    # 指定口径日
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\交易为生")
sys.path.insert(0, str(ROOT / "scripts"))
import report_helpers as H

CACHE = ROOT / "data" / "cache"
DAILY = ROOT / "data" / "daily"


def mark(ok):
    return "OK  " if ok else "缺  "


def guess_day():
    """口径日 = 上一个美股交易日。SGT 跑盘后时美股刚收（SGT 04:00），所以通常是"昨天"；
    周一/周二跑要跳过周末。**只是猜，拿不准就命令行传。**"""
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def find_cache(day):
    """cache 文件名按**抓取日**命名，而 data_date 是口径日——两者常差一天。
    所以按 data_date 找，不按文件名猜。"""
    for p in sorted(CACHE.glob("market_*.json"), reverse=True)[:6]:
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("data_date") == day:
                return p
        except Exception:
            continue
    return None


TEMPLATE_REMINDER = "\n".join([
    "=" * 72,
    "盘后 JSON 必须从模板派生，不要从零手写 out = {...}",
    r"   copy scripts\assemble_template_postmarket.py -> scratchpad\assemble_post_YYYYMMDD.py",
    "   改 DAY / CACHE_KEY，只填标记 ### 手写 ### 的判断内容；骨架 / 字段名不要动。",
    "",
    "   模板会往 JSON 盖 _builder 戳；**QA 查这个戳**——手写把 46 个字段抄齐也过不了。",
    "   骨架已机械生成：三张七列表 / 50MA距离 / 市宽 / SetupA台账 / X台账 / 持仓拆账户 /",
    "   仓位治理 / 代理RS / 对账的 plan+prob（从当天盘前 recon_ledger 复制，prob 盘后不许改）。",
    "",
    "   2026-08-11 之前盘后没有模板：同一套骨架在 scratchpad 里被逐日重写过至少四次，",
    "   每天诞生一次、每天随会话消失。breadth_stage_table 断 12 个交易日就是这么来的。",
    "=" * 72,
])


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else guess_day()
    print(f"\n盘后体检 · 口径日 {day}\n" + "-" * 72)

    ds_hint = day.replace("-", "")
    cpath = find_cache(day)
    print(f"[1] 收盘数据 cache")
    if cpath:
        cache = json.loads(cpath.read_text(encoding="utf-8"))
        n = len(cache.get("metrics") or {})
        print(f"    OK   {cpath.name}（data_date={day}，{n} 只）  → CACHE_KEY = "
              f"\"{cpath.stem.replace('market_', '')}\"")
    else:
        cache = None
        print(f"    缺   没有 data_date={day} 的 market_*.json")
        print(f"         → python scripts/fetch_market_data.py（美股收盘后才有完整数据）")

    print(f"[2] 前置脚本")
    for label, pat, hint in [
        ("财报日历（当天谁真的报了）", "earnings_calendar_*.json",
         f"python scripts/fetch_earnings_calendar.py --date {day}"),
        ("半导体超跌池", "semis_scan_*.json", "python scripts/scan_semis_rsi.py"),
    ]:
        newest = max(CACHE.glob(pat), key=lambda p: p.stat().st_mtime, default=None)
        fresh = newest is not None and newest.stem.endswith(ds_hint[:8]) or (
            newest is not None and newest.stat().st_mtime > 0 and ds_hint in newest.stem)
        # 文件名按抓取日，可能是口径日的次日——两个都认
        nxt = (date.fromisoformat(day) + timedelta(days=1)).strftime("%Y%m%d")
        fresh = newest is not None and (ds_hint in newest.stem or nxt in newest.stem)
        print(f"    {mark(fresh)} {label:<22} {newest.name if newest else '-'}")
        if not fresh:
            print(f"         → {hint}")

    print(f"[3] 当天盘前 JSON（对账台账的来源）")
    pmp = DAILY / f"{day}-premarket.json"
    if pmp.exists():
        pm = json.loads(pmp.read_text(encoding="utf-8"))
        led = pm.get("recon_ledger") or []
        print(f"    OK   {pmp.name}  recon_ledger {len(led)} 条"
              f"（模板会机械复制 plan+prob，**盘后不许改 prob**）")
        for it in led:
            print(f"         · [{it.get('prob')}] {str(it.get('claim'))[:46]}")
        av = (pm.get("today_position") or {}).get("avoid") or []
        if av:
            print(f"    提醒 盘前 avoid 清单 {len(av)} 条——**写迭代前先读一遍**，"
                  f"看正文和台账有没有自相矛盾（2026-08-10 就栽在这）")
    else:
        print(f"    缺   {pmp.name} 不存在 → recon_rows 要手工补，且无法核对正文 vs 台账")

    print(f"[4] Setup A 台账")
    led = H._load_setup_track()["entries"]
    today_n = sum(1 for e in led if e.get("date") == day)
    if today_n:
        print(f"    OK   {day} 已有 {today_n} 条（盘前B 跑过 sync_candidate_track）")
    else:
        print(f"    注意 {day} 一条都没有——盘前B 漏跑了 sync_candidate_track。")
        print(f"         模板会自动补录并关掉自动校验（盘后补跑会拿当天的 bar 当信号日，口径是错的），")
        print(f"         **补完要手工 H.check_invalid_level(tk, 上一交易日, invalid) 复核并写进 note**")
    if cache:
        _, due = H.setup_a_track_rows(cache)
        if due:
            print(f"    待评定 {len(due)} 条满窗：{[d['ticker'] for d in due]}")
            print(f"         → 判完调 H.close_setup_track_entries({{(date,ticker): 'hit'/'miss'}})")

    print(f"[5] 持仓（只认 tradebook，不查 moomoo / 不调 MCP）")
    pos = H.load_tradebook_positions()
    legs = 0
    try:
        tb = json.loads((ROOT / "data/tradebook.json").read_text(encoding="utf-8"))
        legs = sum(1 for t in tb.get("trades", []) for l in t.get("legs", [])
                   if l.get("date") == day)
    except Exception:
        pass
    print(f"    OK   {len(pos)} 笔在持；tradebook 里 {day} 有 {legs} 条成交腿")
    nostop = [p["ticker"] for p in pos if not p.get("stop") and p["ticker"] != "QQQ"]
    if nostop:
        print(f"    提醒 无止损：{nostop}（只提醒不拦截；QQQ 是有意为之已排除）")

    print("\n" + TEMPLATE_REMINDER)
    print(f"\n下一步：copy scripts\\assemble_template_postmarket.py 到 scratchpad，"
          f"DAY=\"{day}\"，跑完再 render_report.py（QA 自动跟着跑，要 0 失败）\n")


if __name__ == "__main__":
    main()
