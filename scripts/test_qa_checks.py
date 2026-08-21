# -*- coding: utf-8 -*-
"""反例测试：新加的检查到底抓不抓得住。\n不测就等于又加了一条自我感觉良好的检查（2026-08-07 Vic：「你都是选个容易qa的qa」）。\n\n加新 @check 时，在这里加一组反例——**至少要有一个「该抓」和一个「不该抓」**。\n"""
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

# ==========================================================================
# ④ 广度类对账条目每份最多 1 条（2026-08-17 定规则，2026-08-19 变成会失败的检查）
#
#    它要防的是「一个预测拆成三条，赌一次押三倍」——T2108 / 涨跌4%+家数 / 5日10日 ratio
#    本来就是同一批数据的不同切法，对会一起对、错会一起错。
#    **同时要测「盘后不查」**：recon_rows 是对盘前台账的机械复制，prob 和 claim 都不许改，
#    在盘后报这个错等于让它为盘前的设计背锅，而且当天无法修复。
# ==========================================================================
print("\n── 广度类对账条目每份最多 1 条 ──")
_HH = Q.helpers


def _mk(*claims):
    return [{"claim": c, "prob": 0.55} for c in claims]


def _has_breadth_err(items, where="recon_ledger"):
    return any("广度类押了" in e for e in _HH.validate_recon_ledger(items, where))


_THREE = _mk("**今日涨 4%+ 家数回到 250 以上**", "**T2108 今日收盘 ≥50**",
             "**10日 ratio 今日不跌破 1.80**", "**XLE 今日收在区间 50% 上方**")
_TWO = _mk("**T2108 今日仍低于 50**", "**跌 4%+ 家数今日回落到 250 以下**",
           "**SMH 今日收盘仍在 50MA 上方**", "**IGV 今日收盘区间位置 ≥40%**")
_ONE = _mk("**T2108 今日仍低于 50**", "**SMH 今日收盘仍在 50MA 上方**",
           "**IGV 今日收盘区间位置 ≥40%**", "**XLE 今日收在区间 50% 上方**")

report("三条广度（8/17 真实台账）", True, _has_breadth_err(_THREE), "涨4%+ / T2108 / 10日ratio")
report("两条广度（8/18 真实台账）", True, _has_breadth_err(_TWO), "T2108 / 跌4%+家数")
report("只有一条广度", False, _has_breadth_err(_ONE), "这是规则允许的形态，不许误报")
report("零条广度也不该抓", False,
       _has_breadth_err(_mk("**SMH 今日收盘仍在 50MA 上方**", "**IGV 收盘区间 ≥40%**",
                            "**XLE 收在区间 50% 上方**", "**VOO 守住 20MA**")), "全是价格类")
report("盘后 recon_rows 不查这条", False, _has_breadth_err(_TWO, "recon_rows"),
       "机械复制盘前台账，当天改不了")

# ==========================================================================
# ⑤ 拆股绊线：存疑的票不许印距52周高／距50MA（2026-08-19 建）
#
#    「该抓」用的是**真实的那次事故**：CRWD 2026-07-02 四拆一，
#    不复权K线让距50MA 报 -42.07%（真值 +11.35%）、距52周高 报 -72.91%（真值 -6.41%）。
#    「不该抓」两种都要测：没标记的票照印不算错、标记了但印 SPLIT_BLOCKED 是**正确写法**。
# ==========================================================================
print("")
print("── 拆股存疑不许印距52周高／距50MA ──")
check_split = next(f for n, f, _ in Q.CHECKS if n.startswith("拆股存疑的票"))
_real_cache_for_report = Q._cache_for_report
FAKE_DAY = "2026-08-18"
FAKE_CACHE = {"data_date": FAKE_DAY, "adjust_type": "none", "metrics": {
    "CRWD": {"close": 212.92, "off_52w_high_pct": -72.91, "dist_ma50_pct": -42.07,
             "split_suspect": True,
             "split_detail": [{"date": "2026-07-02", "prev_date": "2026-07-01",
                               "gap_pct": -74.9, "implied_ratio": "4:1",
                               "vol_restored_x": 0.74, "bars_ago": 33,
                               "affected_windows": [50, 150, 200, 252]}]},
    "PLTR": {"close": 171.54, "off_52w_high_pct": -17.34, "dist_ma50_pct": 25.83,
             "split_suspect": False},
}}
# 打在 _cache_for_report 上：盘前/盘后的口径日解析规则不同（见该函数注释），
# 打在 _cache_for_day 上盘前那条路根本不经过它
Q._cache_for_report = lambda data: FAKE_CACHE if (data or {}).get("date") == FAKE_DAY else None
_B = Q.helpers.SPLIT_BLOCKED


def _d(rows):
    return {"date": FAKE_DAY, "report_type": "premarket",
            "ml_leaders_table": {"headers": [], "rows": rows}}


report("存疑票印了距52周高", True,
       bool(check_split("", _d([["CRWD", "212.92", "-72.91%", "读数"]]))), "CRWD -72.91%")
report("存疑票印了距50MA(ATR)", True,
       bool(check_split("", _d([["CRWD", "212.92", "-2.34×ATR", "读数"]]))), "CRWD -2.34×ATR")
report("存疑票印 SPLIT_BLOCKED", False,
       bool(check_split("", _d([["CRWD", "212.92", _B, "读数"]]))), "正确写法，不许误报")
report("没标记的票照印", False,
       bool(check_split("", _d([["PLTR", "171.54", "-17.34%", "读数"]]))), "PLTR 数据是好的")
report("cache 里没人存疑", False,
       bool(check_split("", {"date": "2026-01-01", "report_type": "premarket"})), "查不到 cache 不误报")

Q._cache_for_report = _real_cache_for_report

# ==========================================================================
# ⑥ 距52周高 vs 独立源（2026-08-19 建）
#
#    这条**要联网**（Yahoo Chart API）。取不到独立源时它自己降级成提醒，
#    所以这里两种结果都算通过——测的是「取到了的话判得对不对」。
#    fixture 直接用真实的 2026-08-18 cache：CRWD 差 66.5pp 该抓、PLTR 差 0.0pp 不该抓。
# ==========================================================================
print("")
print("── 距52周高 vs 独立源 ──")
check_off52 = next(f for n, f, _ in Q.CHECKS if n.startswith("距52周高必须跟独立源"))
_probe = Q._yahoo_off_52w("PLTR", "2026-08-18")
if _probe is None:
    print("   （独立源取不到——离线或被限流，本组跳过；这正是它降级成提醒的那条路径）")
else:
    def _d52(tk, val):
        return {"date": "2026-08-18", "report_type": "premarket",
                "ml_leaders_table": {"headers": [], "rows": [[tk, "1.00", val]]}}

    r_bad = check_off52("", _d52("CRWD", "-72.91%"))
    report("CRWD（cache -72.91 / 真值 -6.41）", True,
           bool(r_bad) and not str(r_bad).startswith(Q.WARN_PREFIX), str(r_bad or "")[:44])
    r_ok = check_off52("", _d52("PLTR", "-17.34%"))
    report("PLTR（cache 和真值一致）", False,
           bool(r_ok) and not str(r_ok).startswith(Q.WARN_PREFIX), str(r_ok or "")[:44])
    r_slv = check_off52("", _d52("SLV", "-47.70%"))
    report("SLV -47.7% 是真实回撤", False,
           bool(r_slv) and not str(r_slv).startswith(Q.WARN_PREFIX), "不许把真跌当脏数据")


print()
print("反例测试" + ("全部通过——这些检查确实会抓东西" if ok else "有不通过项，检查逻辑要改"))
sys.exit(0 if ok else 1)
