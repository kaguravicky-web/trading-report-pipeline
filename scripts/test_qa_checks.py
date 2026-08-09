# -*- coding: utf-8 -*-
"""反例测试：新加的「陈旧结论必须带日期」到底抓不抓得住。
   不测就等于又加了一条自我感觉良好的检查。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"D:\交易为生\scripts")
import qa_report as Q

fn = dict((n, f) for n, f, _ in Q.CHECKS)
check = next(f for n, f, _ in Q.CHECKS if n.startswith("陈旧结论"))

CASES = [
    # (说明, empty-note 内容, 期望是否被抓)
    ("今天犯的原错（无日期）", "本次未跑 Adanos 全量扫描（API curl 在会话里会被安全分类器拦）。", True),
    ("13F 那条原话（无日期）", "13F 已被 13D/13G 取代，不再单独扫描。", True),
    ("带日期的正确写法", "未跑（依据 2026-07-13 实测：curl 被安全分类器拦）。", False),
    ("带短日期也算", "iborrowdesk 7/17 起连续三周不可用。", False),
    ("普通的空，不含断言词", "窗口内无跟踪中的条目。", False),
    ("暂停说明带日期", "每日扫描 2026-08-07 起暂停（iborrowdesk 借券费率源不可用）。", False),
]

TPL = '<html><style>x</style><body><span class="empty-note">%s</span></body></html>'
ok = True
for desc, note, want in CASES:
    got = bool(check(TPL % note, {"report_type": "premarket"}))
    flag = "✅" if got == want else "❌"
    if got != want:
        ok = False
    print("%s %-22s 期望抓=%-5s 实际抓=%-5s | %s" % (flag, desc, want, got, note[:44]))
print()
print("反例测试" + ("全部通过——这条检查确实会抓东西" if ok else "有不通过项，检查逻辑要改"))
