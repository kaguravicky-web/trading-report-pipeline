#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前两段式体检表（2026-07-22建，Vic："盘前报告我想每次分两段跑，白天跑隔夜收盘和x账号，

# ============================================================================
# 🔴 2026-08-12：两段式取消（Vic：「关于盘前的全部删了吧，我打算以后 3-4 点就触发盘前」）。
#    本脚本原来的主要用途是回答「段1 跑到哪了 / 段2 还缺什么 / pm_stale 比例」，
#    现在只剩「今天的前置数据齐了没」这一问。段2 / snap_premarket 相关输出已无意义，
#    保留脚本不删（无 git），但读它的输出时注意：**段2 那一段是历史残留**。
# ============================================================================

4点后跑盘前数据"）。

**段2的会话开工第一件事就是跑这个**——因为省token规则要求每天开新会话，段2那个会话
根本不知道白天段1做了什么。这个脚本一屏之内回答三个问题：
  ①段1跑完了没（cache/setups/x_scan/earnings/semis 五个产物在不在）
  ②段1的判断落盘了没（草稿的 _phase 是几、还差哪些段2字段）
  ③现在能不能跑段2（盘前快照的 pm_stale 比例——SGT 16:00前跑必然全是残留旧数据）

用法：
    python scripts/premarket_status.py              # 看今天
    python scripts/premarket_status.py 2026-07-22   # 看指定日
"""
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import report_helpers as H


def mark(ok):
    return "✅" if ok else "❌"


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    st = H.premarket_phase_status(day)

    print(f"\n=== 盘前两段式状态 · {day} ===\n")

    print("【段1 白天：隔夜收盘 + X扫描】")
    print(f"  {mark(st['cache_exists'])} fetch_market_data.py      cache data_date = {st['cache_data_date']}")
    print(f"  {mark(st['earnings_exists'])} fetch_earnings_calendar.py")
    print(f"  {mark(st['semis_exists'])} scan_semis_rsi.py")
    print(f"  {mark(st['setups_exists'])} scan_setups.py")
    print(f"  {mark(st['xscan_exists'])} X扫描子代理 → x_scan cache")
    ph = st["draft_phase"]
    print(f"  {mark(ph is not None)} 段1草稿落盘            _phase = {ph}"
          + (f"（{st.get('phase1_at')}）" if st.get("phase1_at") else ""))

    print("\n【段2 SGT 16:00后：盘前报价 + 定稿】")
    print(f"  {mark(st['snap_exists'])} snap_premarket.py         {st['snap_stale'] or '（未跑）'}")
    if ph == 1:
        miss = st["phase2_missing"]
        done = len(H.PHASE2_FIELDS) - len(miss)
        print(f"  ⏳ 段2独有字段 {done}/{len(H.PHASE2_FIELDS)}")
        if miss:
            print(f"     还缺：{'、'.join(miss)}")
        pend = st.get("patch_pending") or []
        if pend:
            print(f"  ⏳ 待补盘前列（段1已建骨架，跑 H.patch_premarket_columns 机械补，"
                  f"**别重写判断列**）：{'、'.join(pend)}")
    elif ph == 2:
        print("  ✅ 段2已定稿——可以 render_report.py 了（或已渲染）")

    if st["problems"]:
        print("\n【🔴 阻塞项】")
        for p in st["problems"]:
            print("  " + p)

    # 13F 申报窗口提醒（2026-08-14 Vic：「下周提醒自己每天扫描 13F」）。
    # 🔴 写成代码而不是写进 CONTEXT：日历规则已经在 CONTEXT 里躺了很久，
    #    但「记得去看日历」本身就是要靠人记的事——**开工体检表打印出来才是真提醒。**
    _q_deadlines = ["2026-02-17", "2026-05-15", "2026-08-14", "2026-11-16"]
    _today = date.today()
    for _dl in _q_deadlines:
        _d = date.fromisoformat(_dl)
        _delta = (_today - _d).days
        if -7 <= _delta <= 10:      # 截止日前 7 天到后 10 天：每天都扫
            if _delta < 0:
                _msg = f"距 13F 申报截止（{_dl}）还有 {-_delta} 天"
            elif _delta == 0:
                _msg = f"**今天就是 13F 申报截止日**——大机构通常压线在美东下午提交"
            else:
                _msg = (f"13F 截止后第 {_delta} 天——**大机构的申报现在才陆续可见，"
                        f"这几天才是真正有信息量的窗口**")
            print(f"\n【13F 扫描窗口】{_msg}")
            print("  → curl -s -A \"Vic Trading Research vic@example.com\" "
                  "\"https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&output=atom\"")
            print("  → 只看认识的机构名；小型 RIA 的申报没有信息量，别逐条读")
            break

    print("\n【下一步】")
    if not st["cache_exists"]:
        print("  → 跑段1：python scripts/fetch_market_data.py 开始")
    elif ph is None:
        print("  → 段1数据齐了但判断没落盘。把段1的判断写进 data/daily/"
              f"{day}-premarket.json（用 H.save_premarket_draft(day, out, phase=1)），"
              "否则段2的新会话拿不到你白天想的东西")
    elif ph == 1 and not st["snap_exists"]:
        print("  → 段2第一步：python scripts/snap_premarket.py（确认已过SGT 16:00）")
    elif ph == 1:
        print("  → 段2：读草稿 H.load_premarket_draft(day) → 填 PHASE2_FIELDS → "
              "H.save_premarket_draft(day, out, phase=2) → render_report.py")
    else:
        print("  → 已完成")
    print()


# =========================================================================
# 2026-08-10 加：Vic「但是我记得我们有 pre market builder，为什么格式会错呢」
# ——因为我没用它。模板 scripts/assemble_template.py 只在 CONTEXT 第 2192 行的
# 文件清单里被提到一次；而这个脚本（模板自己写着「每段开工先跑」）之前一个字都没提。
# 把提醒放进唯一一个每天都会被执行到的地方。
# =========================================================================
TEMPLATE_REMINDER = "\n".join([
    "=" * 64,
    "盘前 JSON 必须从模板派生，不要从零手写 out = {...}",
    r"   copy scripts\assemble_template.py  ->  scratchpad\assemble_YYYYMMDD.py",
    "   只改标记 ### 手写 ### 的判断内容；骨架 / 字段名不要动。",
    "   攻守记分板四桶必须齐：upgrade / downgrade / duration / techparity",
    "   动能温度打分九项标签固定（见模板注释）。",
    "   2026-08-10 就是因为绕过模板，攻守记分板、动能打分、futures 表全丢了。",
    "=" * 64,
])


if __name__ == "__main__":
    main()
    print(TEMPLATE_REMINDER)
