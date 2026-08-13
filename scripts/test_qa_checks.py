# -*- coding: utf-8 -*-
"""反例测试：新加的检查到底抓不抓得住。
   不测就等于又加了一条自我感觉良好的检查（2026-08-07 Vic：「你都是选个容易qa的qa」）。

   加新 @check 时，在这里加一组反例——**至少要有一个「该抓」和一个「不该抓」**。
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\交易为生\scripts")
import qa_report as Q

ok = True


def report(desc, want, got, extra=""):
    global ok
    flag = "✅" if got == want else "❌"
    if got != want:
        ok = False
    print("%s %-26s 期望抓=%-5s 实际抓=%-5s | %s" % (flag, desc, want, got, extra[:44]))


# ==========================================================================
# ① 陈旧结论必须带日期（2026-08-07 建）
# ==========================================================================
print("── 陈旧结论必须带日期 ──")
check_stale = next(f for n, f, _ in Q.CHECKS if n.startswith("陈旧结论"))
CASES = [
    ("今天犯的原错（无日期）", "本次未跑 Adanos 全量扫描（API curl 在会话里会被安全分类器拦）。", True),
    ("13F 那条原话（无日期）", "13F 已被 13D/13G 取代，不再单独扫描。", True),
    ("带日期的正确写法", "未跑（依据 2026-07-13 实测：curl 被安全分类器拦）。", False),
    ("带短日期也算", "iborrowdesk 7/17 起连续三周不可用。", False),
    ("普通的空，不含断言词", "窗口内无跟踪中的条目。", False),
    ("暂停说明带日期", "每日扫描 2026-08-07 起暂停（iborrowdesk 借券费率源不可用）。", False),
]
TPL = '<html><style>x</style><body><span class="empty-note">%s</span></body></html>'
for desc, note, want in CASES:
    report(desc, want, bool(check_stale(TPL % note, {"report_type": "premarket"})), note)

# ==========================================================================
# ② 盘后字段集 == 模板字段集（2026-08-11 建，Vic：「我们以后都用 builder 跑」）
#
#    它要防的是两件**方向相反**的事，所以两个都得测：
#    · 多字段 = 自造（8/10 盘前那次凭空长出 scoreboard_rows 就是这种）
#    · 少字段 = 静默丢失（breadth_stage_table 从 7/28 起断 12 个交易日就是这种）
# ==========================================================================
print("\n── 盘后字段集 == 模板字段集 ──")
check_fields = next(f for n, f, _ in Q.CHECKS if n.startswith("盘后字段集"))
TPL_FIELDS = Q._template_fields("assemble_template_postmarket.py", Q.RETIRED_POSTMARKET_FIELDS)
base = {k: "x" for k in TPL_FIELDS}
base["report_type"] = "postmarket"

report("完整字段集", False, bool(check_fields("", base)), "%d 个字段全在" % len(TPL_FIELDS))

d = dict(base); d["my_new_invented_table"] = []
report("凭空多一个字段", True, bool(check_fields("", d)), "my_new_invented_table")

d = dict(base); d.pop("iterations")
report("静默少一个字段", True, bool(check_fields("", d)), "少了 iterations")

d = dict(base); d["breadth_stage_table"] = {}
report("退役字段出现不算自造", False, bool(check_fields("", d)), "breadth_stage_table（2026-08-11 退役）")

d = dict(base); d["report_type"] = "premarket"
report("盘前报告不管", False, bool(check_fields("", d)), "report_type=premarket")

# ==========================================================================
# ③ 盘后报告必须由 builder 生成（2026-08-11 建，Vic：「这次不会丢了吗」）
#
#    ②只查字段名——**手写把 46 个键抄齐照样能过**。这条查 _builder 戳，
#    是唯一不依赖"记得用模板"的那道锁。
# ==========================================================================
print("\n── 报告必须由 builder 生成（盘前盘后都查）──")
check_stamp = next(f for n, f, _ in Q.CHECKS if n.startswith("报告必须由 builder"))

d = {"report_type": "postmarket", "date": "2026-08-12"}
report("新报告没戳", True, bool(check_stamp("", d)), "date=2026-08-12，无 _builder")

d = {"report_type": "postmarket", "date": "2026-08-12",
     "_builder": "assemble_template_postmarket.py"}
report("新报告有戳", False, bool(check_stamp("", d)), "有 _builder")

d = {"report_type": "postmarket", "date": "2026-08-10"}
report("模板建成前的旧报告豁免", False, bool(check_stamp("", d)), "date=2026-08-10 < 2026-08-11")

d = {"report_type": "premarket", "date": "2026-08-12"}
report("盘前没戳也抓", True, bool(check_stamp("", d)), "盘前模板同批盖戳，一起查")

d = {"report_type": "premarket", "date": "2026-08-12", "_builder": "assemble_template.py"}
report("盘前有戳", False, bool(check_stamp("", d)), "有 _builder")

d = {"report_type": "weekly", "date": "2026-08-12"}
report("周报暂不查（没模板）", False, bool(check_stamp("", d)), "report_type=weekly")


# ==========================================================================
# ④ phase 桶必须恰好覆盖盘前模板字段集（2026-08-11 建）
#
#    这条跟前面几条不一样：**它查的不是某一份报告，是流水线本身**，
#    所以反例不能靠伪造 data，要靠临时改 report_helpers 的三个桶再还原。
#
#    为什么必须有：两段式下段1 用 keep=PHASE1|PHASE2_PATCH 过滤、段2 只补 PHASE2_FIELDS。
#    模板里有、三个桶都没有的字段 = **段1 丢掉、段2 不补回 → 永久消失，而报告照样渲染出来**。
#    已发生三次：8/3（ftd / 仓位治理）、8/7（事件缺口候选一个没进报告）、
#    8/11（bam / dispersion / stop_proximity / special_readthrough / adanos_scan_note /
#    recon_prob_note 等 11 个，是 Vic 问「用了 builder 对吗」时顺手查出来的）。
# ==========================================================================
print("\n── phase 桶必须恰好覆盖盘前模板字段集 ──")
check_phase = next(f for n, f, _ in Q.CHECKS if n.startswith("phase 桶"))
import report_helpers as _H

_p1 = list(_H.PHASE1_FIELDS)
try:
    report("当前三个桶就是齐的", False, bool(check_phase("", {})), "线上状态应为全覆盖")

    _H.PHASE1_FIELDS.remove("bam")
    report("桶里少一个模板字段", True, bool(check_phase("", {})),
           "拿掉 bam——正是 8/11 真实漏掉的那一批之一")
    _H.PHASE1_FIELDS[:] = _p1

    _H.PHASE1_FIELDS.append("my_invented_field")
    report("桶里多一个模板没有的", True, bool(check_phase("", {})), "多出 my_invented_field")
    _H.PHASE1_FIELDS[:] = _p1

    report("还原后重新变干净", False, bool(check_phase("", {})), "确认前面的改动已还原")
finally:
    _H.PHASE1_FIELDS[:] = _p1

print()
print("反例测试" + ("全部通过——这些检查确实会抓东西" if ok else "有不通过项，检查逻辑要改"))
sys.exit(0 if ok else 1)
