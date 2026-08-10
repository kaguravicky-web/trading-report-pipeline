# -*- coding: utf-8 -*-
"""报告格式QA闸门（2026-07-28建）。

起因：Vic同一批格式问题反复提——A/B/C三级格式统一提了三次（7/12、7/27、7/28）、
红绿灯提了三次、小结不分段提了两次。根因不是"某天手滑"，而是**每开一个新会话，
格式约定就要靠人重新记一遍**，记漏了报告照样能渲染出来，没人拦。

所以规则不写进文档，写进这个脚本：每条格式约定 = 一条会失败的检查。
渲染完跑一次，红了就是漂了。新会话不需要记住任何事，跑它就行。

    python scripts/qa_report.py output/premarket/2026-07-28-premarket.html
    python scripts/qa_report.py --today          # 今天的盘前+盘后都查

规则来源全部是Vic原话，每条注明日期，避免以后有人"优化"掉。

🔴**通过很久的检查不要删（2026-08-06 讨论过一次，结论：不删）。**
Vic 当时提「6天后全部通过的项目就不用再QA，删除就可以了吧」。
**通过 ≠ 问题解决，是检查在按着它**——根因（每开新会话格式约定靠人重新记）一天没变，
删掉漂移就会回来。真正想解决的是"18行OK刷屏"，已改成**默认只打失败/提醒**，
全通过就一行；要看全部加 `--verbose`。
**唯一可以退休的标准不是"通过久了"，是"失败路径在代码层面已不存在"**
（例：A/B/C 旧字段现在在渲染器里直接 raise，走不到那条路）——那种删了不开口子。

结构规格见下方 REPORT_SPEC：盘前/盘后/周报/月报各自的必备节+顺序+必填字段，
拦「少一节 / 顺序变了 / 同一 anchor 渲染两次」。改渲染器顺序时必须同步改它。

═══════════════════════════════════════════════════════════════════════════
🔴 2026-08-10 Vic：「我感觉 QA 以后，质量怎么变差了，变得认不出。。。」——**他是对的。**

时间线：7/27 攻守记分板被拆成两张表 → **7/28 QA 建成** → 7/29~8/03 动能温度打分
九个标签被逐步换掉。**漂移是在 QA 建成前后一两天开始的，而 QA 一次都没拦住。**

三个原因，都是这个文件自身的设计缺陷：
 ① **查的全是表面格式**——emoji、字面星号、小数位、列宽、指数顺序、中文化。
    8/10 之前**没有一条在查「内容还是不是原来那个东西」**。报告可以全绿，同时面目全非。
 ② **REPORT_SPEC.required_fields 只列 15 个字段**，盘前实际 78 个，
    等于宣告其余 63 个「可有可无」，于是结构被放开手改。
 ③ **最危险的一层：我每次加检查都照「当时最近那份报告」写。**
    8/10 上午我就把漂移后的 6 条计分板写成了 SCOREBOARD_CONDITIONS——
    **再晚一步，漂移就被 QA 盖章成「正确」永久固化了。**

**所以这个文件从今天起多一条元规则：**
**每条涉及「内容口径」的检查，必须在注释里写明它照的是哪一份报告、哪一天。**
改这类检查的期望值时，同样要写明新基线是哪一天、为什么换。
没有日期出处的口径检查 = 把某次漂移写成了标准。
当前口径基线：攻守记分板 / 动能温度打分 = **2026-07-23 ~ 07-24**（11 行 4 桶的成熟形态）。
═══════════════════════════════════════════════════════════════════════════
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_helpers as helpers  # noqa: E402  校验口径只在 helpers 定义一处


def _text(html: str) -> str:
    """取<style>之后的正文可见文本。"""
    body = html[html.find("</style>"):]
    return re.sub(r"<[^>]+>", " ", body)


CHECKS = []
WARN_PREFIX = "[规则生效前·仅记录] "
VERBOSE = [False]   # --verbose 时打印全部通过项；默认只打失败/提醒


def check(name, fatal=True):
    def deco(fn):
        CHECKS.append((name, fn, fatal))
        return fn
    return deco


# --------------------------------------------------------------------------
@check("红绿灯emoji（Vic 7/22、7/27、7/28三次提「报告中还是有很多红绿灯」）")
def _no_lights(html, data):
    body = html[html.find("</style>"):]
    found = re.findall(r"[🔴🟢🟡🟠⚪⚫✅❌]|⚠️?", body)
    if found:
        return f"正文出现{len(found)}个红绿灯/勾叉emoji：{sorted(set(found))}——" \
               "严重度应由CSS配色承载（badge/callout kind/sign_class/色条），emoji是第四层冗余"


@check("A/B/C三级格式统一（Vic 7/12、7/27、7/28三次提）")
def _abc_unified(html, data):
    if data is None:
        return
    legacy = [k for k in ("watchlist_a", "watchlist_b_table", "watchlist_c") if data.get(k)]
    if legacy:
        return f"用了旧字段{legacy}——三级会渲染成「A卡片+B表格+C灰块」三种格式；" \
               "请合并进 watchlist_abc（每条带grade）"
    if "A级（允许执行）" in html or "B级（观察为主）" in html:
        return "出现旧版A/B/C分块小标题，说明走了legacy渲染分支"


@check("小结分段（Vic 7/22「小结格式都改好点啊，不分行目前很难读的」）")
def _notes_split(html, data):
    if data is None:
        return
    bad = []
    for k, v in data.items():
        if k.startswith("_"):          # _phase1_note等内部元数据不是给人读的小结
            continue
        if not (k.endswith("_note") or k in ("setup_conclusion", "x_sentiment_note")):
            continue
        if isinstance(v, str) and len(v) > 160 and "；" not in v and "\n" not in v:
            bad.append(f"{k}({len(v)}字)")
    if bad:
        return f"这些小结是一整段没有分段点：{bad}——用「；」分句，渲染器会拆成bullet"


@check("literal ** 星号（Vic 7/22：一份报告里214处**当字面星号渲染）")
def _no_literal_stars(html, data):
    n = _text(html).count("**")
    if n:
        return f"正文出现{n}处字面**——该字段没走rich()，粗体没生效"


@check("中文化（Vic 7/28「方法5 · X trader setup提取 变成英文的了」）")
def _chinese(html, data):
    if data is None:
        return
    bad = []
    for key, field in (("x_sentiment_macro", "summary"), ("x_sentiment_stocks", "note")):
        for i, it in enumerate(data.get(key) or []):
            s = str(it.get(field, ""))
            if not s:
                continue
            # 中文字符占比过低 = 没翻译（允许纯数据/代码类短句）
            zh = len(re.findall(r"[一-鿿]", s))
            if len(s) > 40 and zh / max(len(s), 1) < 0.15:
                bad.append(f"{key}[{i}]")
    if bad:
        return f"这些X扫描条目还是英文：{bad[:8]}{'…' if len(bad) > 8 else ''}——" \
               "X扫描子代理返回英文时必须翻成中文再落盘"


@check("小数位（Vic：统一2位）", fatal=False)
def _decimals(html, data):
    body = html[html.find("</style>"):]
    # Brier 分数天然需要 3 位（0.121 和 0.127 的差别有意义），单独豁免；
    # 豁免的是**带 brier-val 类的单元格**，不是"所有三位小数"，别开成通用口子。
    body = re.sub(r'<span class="brier-val[^"]*">[^<]*</span>', "", body)
    n = len(re.findall(r">\s*-?\d+\.\d{3,}\s*<", body))
    if n:
        return f"{n}处3位以上小数"


@check("情景概率合计100（2026-07-08起每个情景必须带prob）")
def _scenario_prob(html, data):
    if data is None:
        return
    sc = data.get("playbook_scenarios") or []
    if not sc:
        return
    probs = [s.get("prob") for s in sc]
    if any(p is None for p in probs):
        return "有情景没写prob"
    if sum(probs) != 100:
        return f"情景概率合计{sum(probs)}≠100"


# ❌ 已删除「对账台账可证伪（盘前必须5-8条）」——2026-08-07 实测 56 份报告 **0 次命中**。
#    条数从来没写错过，这条检查只是让 QA 看起来更满。ledger 的真实风险不是"条数不够"，
#    是"写了一堆不可能 miss 的废条"（VIX<22 那条从建表起没 miss 过一次，被 Vic 8/7 亲手删掉）——
#    当时的结论是"**那个用数字是查不出来的**，只能靠写的时候自问有没有可能 miss"。
#    ✅ 2026-08-08 推翻这个结论：查不出来是因为**没让自己写下事前概率**。
#    Vic 抓包 8/3–8/6：报出 85%，剔掉自控条目和送分题后真预测只有 60%。
#    补上 prob 之后，"不可能 miss 的废条"就是一个可判定的数值条件了——见下面两条检查。


# 新规则从 2026-08-08 起生效。更早的报告是在旧口径下写的，prob 只能事后回填，
# 回填出来的「违规」是历史证据不是今天的缺陷——所以对它们降级为提醒。
# 这不是给规则开后门：**日期之后的报告一条都不放过**，分档标准写死在这里而不是逐份豁免。
RECON_PROB_RULE_FROM = "2026-08-08"


def _pre_rule(data) -> bool:
    return (data.get("date") or "") < RECON_PROB_RULE_FROM


@check("对账条目必须带事前概率且不许堆送分题（2026-08-08 Vic：「的确是自己评的太好了」）")
def _recon_prob(html, data):
    if data is None:
        return
    items = data.get("recon_ledger") or data.get("recon_rows") or []
    if not items:
        return
    where = "recon_ledger" if data.get("recon_ledger") else "recon_rows"
    errs = helpers.validate_recon_ledger(items, where)
    if not errs:
        return
    msg = "；".join(errs[:3]) + ("" if len(errs) <= 3 else f"（共{len(errs)}条）")
    return (WARN_PREFIX + msg) if _pre_rule(data) else msg


@check("盘后必须报 Brier 而不只是命中率（送分题堆出来的「满分日」要能被看穿）")
def _recon_brier(html, data):
    if data is None or not data.get("recon_rows"):
        return
    st = helpers.brier_score(data["recon_rows"])
    if st.get("no_prob"):
        return f"{st['no_prob']}条已判定的对账行没有prob，Brier算不全"
    if st.get("brier") is None:
        return "recon_rows全部无法评分（既没prob也没result）"
    if "brier-line" not in html:
        return "算出了Brier但没渲染到报告里（静默丢失）"


@check("指数顺序统一（Vic 7/28：三处各排各的，且SPY/VOO并列重复）")
def _index_order(html, data):
    if data is None:
        return
    sys.path.insert(0, str(ROOT / "scripts"))
    import report_helpers as H
    want = H.INDEX_ORDER
    bad = []
    # "不要写SPY"针对的是**我们自己的**指数口径，不针对引用别人的话——
    # X账号原话里说"等SPY站上50日均线"，改成VOO就是曲解原文（2026-07-30放宽）。
    # 所以查数据字段而不是渲染后的HTML，并跳过X扫描来源的字段。
    SKIP = ("x_sentiment_macro", "x_sentiment_stocks", "x_sentiment_note",
            "x_sentiment_macro_summary", "x_watch_table", "x_watch_note",
            "news_today", "news_tracking")

    def _spy_hits(obj, path=""):
        if isinstance(obj, str):
            # 不能用 \b：中文也算word字符，"SPY守住"里Y和守之间没有词边界，\bSPY\b 会漏
            return [path] if re.search(r"(?<![A-Za-z])SPY(?![A-Za-z])", obj) else []
        if isinstance(obj, list):
            return [p for i, v in enumerate(obj) for p in _spy_hits(v, f"{path}[{i}]")]
        if isinstance(obj, dict):
            return [p for k, v in obj.items() for p in _spy_hits(v, f"{path}.{k}")]
        return []

    hits = [p for k, v in data.items() if k not in SKIP and not k.startswith("_")
            for p in _spy_hits(v, k)]
    if hits:
        bad.append(f"这些字段仍出现SPY（应统一为VOO）：{sorted(set(h.split('.')[0].split('[')[0] for h in hits))}")
    for field, get in (("atr_extension_table", lambda r: r.get("ticker")),
                       ("index_table", lambda r: r[0])):
        v = data.get(field)
        rows = v.get("rows") if isinstance(v, dict) else v
        if not rows:
            continue
        got = [str(get(r)).split()[0] for r in rows]
        if got != want:
            bad.append(f"{field} 顺序是 {got}，应为 {want}")
    for grp in data.get("sector_rs_tables") or []:
        if "指数" in (grp.get("title") or ""):
            got = [str(r[0]).split()[0] for r in grp.get("rows", [])]
            if got != want:
                bad.append(f"指数基准组 顺序是 {got}，应为 {want}")
    if bad:
        return "；".join(bad) + "（顺序常量在 report_helpers.INDEX_ORDER，改那里不要各表各改）"


@check("涨跌%着色（2026-07-29 Vic：「自提及的涨跌颜色没有了」）")
def _pct_colored(html, data):
    body = html[html.find("</style>"):]
    # 形如 <td ...>+8.97%</td> 的单元格必须带 up/dn 类；没带说明该列漏进num_cols了
    bad = []
    # 2026-08-10：原正则的 (?:<[^>]+>)* 会**跨过 </td>**，把「前面的空单元格 + 后面着色的单元格」
    # 拼成一次匹配，attrs 取自空单元格 → 误报。内层跳标签必须排除 </td>。
    for m in re.finditer(r'<td([^>]*)>\s*(?:<(?!/td)[^>]+>)*\s*([+-]\d+(?:\.\d+)?%)'
                         r'\s*(?:</(?!td)[^>]+>)*\s*</td>', body):
        attrs, val = m.group(1), m.group(2)
        if "up" not in attrs and "dn" not in attrs:
            bad.append(val)
    if bad:
        return (f"{len(bad)}个涨跌%单元格没有涨跌色（如 {bad[:6]}）——"
                "该列要写进表的 num_cols，渲染器才会套 sign_class")


# ❌ 已删除「居中列表头对齐」——2026-08-07 实测 **0/56 命中**。
#    2026-07-29 加它是为了修一次具体的视觉错位，但那次之后 build_table 的 _hcls() 已经
#    从 center_cols 自动推导表头 class，**渲染层已经收口了**，这条检查是收口之后的冗余复制。


@check("其他资产表已退役行（2026-07-29 Vic：「VIX1D 这里还没改，说好不要了」）")
def _retired_rows(html, data):
    if data is None:
        return
    t = data.get("other_assets_table") or {}
    # CONTEXT.md「B·其他资产」定的规则：VIX1D折进VIX那行的信号列判Contango，不单列；
    # MOVE整行已于2026-07-21删除。这两条以前只写在文档里，靠人记，于是又漏了一次。
    RETIRED = {"VIX1D": "折进VIX那行的信号列判Contango，不单列",
               "MOVE": "2026-07-21起整行删除"}
    bad = [f"{r[0]}（{RETIRED[str(r[0]).split()[0]]}）"
           for r in t.get("rows", [])
           if r and str(r[0]).split()[0] in RETIRED]
    if bad:
        return "其他资产表出现已退役的行：" + "；".join(bad)


@check("badges渲染（2026-08-01：盘前/盘后定义了badges却没渲染，静默丢失）", fatal=False)
def _badges(html, data):
    if data is None or not data.get("badges"):
        return
    if 'class="badges"' not in html:
        return (f'JSON里有{len(data["badges"])}条badges但header没渲染——'
                "三个渲染器的header必须都带 {badges}")


@check("表格列宽对齐（2026-08-01与周报对齐时发现盘前有4张裸table）")
def _table_class(html, data):
    # 2026-08-07 从 fatal=False 升级为 fatal=True。原因是 Vic 指出的 QA 毛病：
    # 这条 56 份报告里报了 **45 次、一次都没被修过**——因为它只是"提醒"。
    # 同日已在 build_table 里加了自动兜底（无 col_widths 时按列数生成），
    # 现在再触发就说明有绕过 build_table 的手写 <table>，那是真问题，必须拦。
    body = html[html.find("</style>"):]
    n = len(re.findall(r"<table>", body))
    if n:
        return (f"{n}张表没有table_class/colgroup——build_table 已自动兜底，"
                "还裸着说明这张表是手写 HTML 绕过了 build_table")


@check("陈旧结论必须带日期（2026-08-07 Vic：「要加」——Adanos/13F 两次都栽在照抄旧结论）")
def _stale_claims(html, data):
    """空节/占位说明里若出现「不可用」类断言却不注明依据日期，提示一次。

    起因：2026-08-07 同一天栽了两次，都是**陈旧假设被当成当前事实引用**——
      · Adanos 写「API curl 被安全分类器拦」（7/13 的实测），
        而现在取数走的是 fetch_adanos() 的 urllib，**根本不经过 curl**，数据一直在 cache 里；
      · 13F 写成已被 13D/13G「取代」（7/05 的决定），
        而 13F 是季度性的，**Q2 截止日 8/14 就在眼前**。
    两次都不是数据错，是**判断的保质期到了没人知道**。带上日期，陈旧度就摆在句子里。
    """
    if data is None:
        return
    # ⚠️词表是反例测试逼出来的：初版写「被拦」，结果连当天原错
    # 「API curl 在会话里会被安全分类器拦」都抓不到（"被"和"拦"中间隔了字）。
    # 改用单字/短词匹配，宁可多提示一次。改这个词表后**必须重跑
    # scratchpad/test_new_check.py 的反例**，别再凭感觉改。
    STALE_WORDS = ("拦", "不可用", "失败", "无响应", "拿不到", "失效", "403",
                   "取代", "未跑", "挂了", "不支持", "已退休", "废弃")
    body = html[html.find("</style>"):]
    bad = []
    for m in re.finditer(r'<span class="empty-note">(.*?)</span>', body, re.S):
        txt = re.sub(r"<[^>]+>", "", m.group(1))
        if any(w in txt for w in STALE_WORDS) and not re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}", txt):
            bad.append(txt[:42])
    if bad:
        return ("这些「不可用」类断言没写依据日期，无法判断是不是过期结论："
                + " ／ ".join(bad)
                + "\n      写成「未跑（依据 7/13 实测 curl 被拦）」这种形式——"
                  "三周前的判断一眼可疑，当天的判断一眼可信")


# ❌ 已删除「仓位治理必须单列标红」——2026-08-07 实测 **0/56 命中**。
#    渲染器里 gov_pre/gov 两处都是「有 rows 就渲染 gov-head」，数据在表就一定在，
#    这条检查等于在验证一行 if 语句。真正会出问题的是 tradebook 补录滞后，
#    **那是记录问题不是渲染问题，QA 查不到也不该查**（见「仓位治理只提醒不拦截」）。


@check("字段写了却没被渲染（2026-08-05：event_gap_candidates 整块静默丢失）")
def _orphan_fields(html, data):
    """字段名校验只查「已知 builder 的键名对不对」，查不出「全新字段根本没人渲染」。
    2026-08-05 就是这么丢的：event_gap_candidates 写进 JSON、渲染器不认识、整块消失且不报错。
    这条查的是：JSON 里有内容的字段，其内容在 HTML 里能不能找到痕迹。"""
    if data is None:
        return
    # 用「剥掉标签的正文」比对，且探针本身要去掉 markdown 记号——
    # 否则 `**IGV` 这种探针永远匹配不上（渲染后已变成 <strong>IGV），会误报一大片
    # 2026-08-10：探针里含 < > & 的字段会误报——它们在 HTML 里是 &lt; &gt; &amp;，
    # 剥标签之后仍是实体形式，跟原文对不上（stop_proximity_note 的「距止损 <0.7ATR」中过一次）。
    # 两边都做实体反转义再比。
    import html as _htmlmod
    plain = re.sub(r"\s+", "", _htmlmod.unescape(_text(html)))

    def _probe(s):
        s = _htmlmod.unescape(str(s))
        s = re.sub(r"[*#`\s]|🔴|🟢|⚠️|🎯|⭐|️", "", s)
        return s[:10]

    SKIP = {"report_type", "date", "generated_at", "_phase", "_phase1_at", "_phase1_note",
            "_phase2_at", "_phase2_skipped", "_phase1_signal_light_note", "ftd",
            "footer_sources", "news_sources", "badges", "subtitle", "regime_triggers",
            "signal_light", "playbook_scenarios", "today_position", "key_takeaways"}
    bad = []
    for k, v in (data or {}).items():
        if k in SKIP or k.startswith("_") or not v:
            continue
        probe = None
        if isinstance(v, list) and v and isinstance(v[0], dict):
            probe = _probe(v[0].get("ticker") or v[0].get("handle") or v[0].get("label") or "")
        elif isinstance(v, dict) and v.get("rows") and v.get("headers"):
            # 表格dict：拿第一行第一格当探针。position_governance_table 就是从这个缺口漏掉的
            r0 = v["rows"][0]
            probe = _probe(r0[0] if isinstance(r0, list) and r0 else "")
        elif isinstance(v, str) and len(v) > 40:
            probe = _probe(v)
        if probe and len(probe) >= 4 and probe not in plain:
            bad.append("%s（探针「%s」在正文里找不到）" % (k, probe))
    if bad:
        return ("这些字段有内容但渲染结果里找不到，很可能整块被静默丢弃：\n      "
                + "；".join(bad[:5])
                + "\n      改法：给它写一个 build_xxx() 并接进 render_premarket/render_postmarket，"
                  "同时注册进 render_report.py 末尾的字段名校验表")


@check("量比必须带位置标注（2026-08-05 Vic：「同一个缩量在不同位置含义完全相反，"
       "这个加入我们的框架，不要只记住」）")
def _volume_context(html, data):
    """2026-08-04 的实际教训：我把 8/3(Day 3) 缩量当成「FTD 质量存疑」写进盘前，
    而 rally attempt 期的缩量是加分项（Wyckoff no supply / Minervini VDU）。
    根因是量比在表里就是个裸数字「0.89×」，读法全靠人每次记住——记漏了报告照样渲染，没人拦。
    收口办法：量比一律走 report_helpers.volume_read()，读法跟着位置自动出来。本检查拦「漂回裸数字」。"""
    if data is None:
        return
    bad = []
    for key, col in (("strong_sector_setups_table", 6), ("ftd_table", 3)):
        t = data.get(key)
        if not isinstance(t, dict):
            continue
        for r in t.get("rows", []):
            if len(r) <= col:
                continue
            cell = str(r[col])
            if re.fullmatch(r"\s*[\d.]+\s*[x×]\s*", cell):
                bad.append("%s[%s]=%s" % (key, r[0], cell.strip()))
    if bad:
        return ("这些量比格是裸数字、没带位置读法（回踩类缩量=加分／突破类缩量=减分）：\n      "
                + "、".join(bad[:6])
                + "\n      改法：该列用 report_helpers.volume_read(context, vol_ratio)[1] 生成，"
                  "context 取 pullback／attempt／breakout，不要自己写判断文字")


@check("字段名校验（渲染器静默丢失防护，2026-07-28建）")
def _fieldnames(html, data):
    if data is None:
        return
    sys.path.insert(0, str(ROOT / "scripts"))
    import render_report
    errs = render_report.validate_data(data)
    if errs:
        return "键名写错会被静默渲染成空白：\n      " + "\n      ".join(errs)


# =========================================================================
# 🔴 四种报告的结构规格（2026-08-06 Vic：「现在能把格式固定下来吗（盘前盘后周报月报）？
#    不要漂移，加入 qa」）
#
# 前面那些 @check 管的是**格式细节**（emoji/小数位/着色/列宽）。这一节管的是**结构**：
# 哪些节必须有、顺序是什么、哪些字段不能空。结构漂移比格式漂移更隐蔽——
# 少一节不会报错，报告照样渲染，只是那部分内容永远不出现（2026-08-05 一次抓出 7 处就是这类）。
#
# 顺序按 render_report.py 里 section() 的实际调用顺序，改渲染器顺序时这里要同步改，
# 否则 QA 会红——**这是故意的**：顺序变更必须是有意的，不能是某次改动的副作用。
REPORT_SPEC = {
    "premarket": {
        "sections": ["signal", "risk", "scoreboard", "breadthscore", "macro", "gate",
                     "positions", "news", "setup", "scenario", "wrapup"],
        "optional": ["ftd", "bounce"],          # FTD 2026-08-06 起暂停；反弹品类等 Vic 指令
        "required_fields": ["signal_light", "risk_checklist", "gate_scoreboard_rows",
                            "breadth_score_rows", "sector_rs_tables", "unilateral_scan_table",
                            "etf_table", "positions_moomoo_table", "positions_longbridge_table",
                            "strong_sector_setups_table", "watchlist_abc", "playbook_scenarios",
                            "key_takeaways", "today_position", "recon_ledger"],
        "phase1_exempt": ["premarket_movers", "watchlist_abc", "playbook_scenarios",
                          "key_takeaways", "today_position", "recon_ledger"],
    },
    "postmarket": {
        "sections": ["recon", "hitrate", "lessons", "newswatch", "close", "breadth",
                     "setupa", "xwatch", "earnings", "positions", "outlook"],
        "optional": ["ml"],
        "required_fields": ["recon_rows", "hit_rate_stats", "iterations", "news_tracking",
                            "index_table", "sector_table", "breadth_live_table",
                            "positions_moomoo_table", "next_day_outlook"],
        "phase1_exempt": [],
    },
    "weekly": {
        "sections": ["core", "regime", "market", "winners", "lastweek", "trades",
                     "system", "correction", "macro", "crossval"],
        "optional": [], "required_fields": [], "phase1_exempt": [],
    },
    "monthly": {
        "sections": ["core", "market", "trades", "system", "framework", "crossval", "nextmonth"],
        "optional": [], "required_fields": [], "phase1_exempt": [],
    },
}


@check("报告结构固定（2026-08-06 Vic：「把格式固定下来，盘前盘后周报月报，不要漂移」）")
def _structure(html, data):
    rt = (data or {}).get("report_type") or ""
    if rt not in REPORT_SPEC:
        return
    spec = REPORT_SPEC[rt]
    got = re.findall(r'<section id="([^"]+)"', html)
    dup = [a for a in set(got) if got.count(a) > 1]
    want = [a for a in spec["sections"]]
    got_req = [a for a in got if a in want]
    bad = []
    missing = [a for a in want if a not in got]
    if missing:
        bad.append("缺少必备节：%s" % missing)
    if dup:
        bad.append("同一个 anchor 渲染了两次（会导致页内跳转失效）：%s" % dup)
    if got_req != want and not missing:
        bad.append("节顺序变了：实际 %s，规格 %s" % (got_req, want))
    # 字段必填（段1草稿豁免那些本来就属段2的字段）
    exempt = set(spec["phase1_exempt"]) if (data or {}).get("_phase") == 1 else set()
    empty = [f for f in spec["required_fields"] if f not in exempt and not (data or {}).get(f)]
    if empty:
        bad.append("必填字段为空：%s" % empty)
    if bad:
        return ("；".join(bad)
                + "\n      规格在 qa_report.REPORT_SPEC，改渲染器顺序时要同步改这里"
                  "——顺序变更必须是有意的，不能是某次改动的副作用")


@check("空节必须带三态标记（2026-08-07 Vic：「没扫出来不要空着，放『无』，这样就不会漏掉」）")
def _empty_states(html, data):
    """空内容的节必须显式写出是哪一种"空"，不能只留个标题、更不能整节消失。

    三态：无（跑了没有）/ 暂停（主动 park）/ 数据缺（源不可用）。
    这条检查存在的理由是今天连出两次事故——FTD 暂停让「02 市场广度」整节消失、
    A 级为空让 Setup A 对账整节消失。**根因都是「内容为空 → 整节不 append」。**
    """
    bad = []
    # ①每个 <section> 都必须有实质内容或三态标记
    for m in re.finditer(r'<section id="([^"]+)">(.*?)</section>', html, re.S):
        anchor, body = m.group(1), m.group(2)
        stripped = re.sub(r"<h2>.*?</h2>", "", body, flags=re.S)
        text = re.sub(r"<[^>]+>", "", stripped).strip()
        if not text:
            bad.append("节 `%s` 完全空白，既没内容也没三态标记" % anchor)
    # ②三态标记的 class 必须是已定义的三个之一（防手写错拼）
    for cls in re.findall(r'class="empty-tag ([^"]+)"', html):
        if cls not in ("es-none", "es-parked", "es-nodata"):
            bad.append("未知的空节状态 class：%s（只能是 es-none / es-parked / es-nodata）" % cls)
    # ③parked 的模块不该同时还渲染大段说明（说明进 CONTEXT.md，报告里每天重复是噪音）
    if data and (data.get("ftd") or {}).get("parked") and data.get("ftd_note"):
        bad.append("FTD 已 parked，JSON 里不该再带 ftd_note——暂停期只留标题+「暂停」标记")
    if bad:
        return ("；".join(bad)
                + "\n      空节用 render_report.empty_section() / empty_body(state, note)，"
                  "state ∈ none|parked|nodata")


# --------------------------------------------------------------------------
def run(html_path: Path, json_path: Path = None):
    html = html_path.read_text(encoding="utf-8")
    data = None
    if json_path and json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))

    print(f"\n=== QA · {html_path.name} ===")
    fails = warns = 0
    for name, fn, fatal in CHECKS:
        try:
            msg = fn(html, data)
        except Exception as e:                      # 检查本身出错不该挡住报告
            print(f"  ?  {name} —— 检查异常：{e}")
            continue
        if msg:
            # 检查函数可以给消息加 WARN_PREFIX，把这一条**本次**降级为提醒
            # （用于「规则生效前的历史报告」这类按日期分档的情况）。
            if str(msg).startswith(WARN_PREFIX):
                warns += 1
                print(f"  !  {name}\n      {msg}")
                continue
            if fatal:
                fails += 1
                print(f"  X  {name}\n      {msg}")
            else:
                warns += 1
                print(f"  !  {name}\n      {msg}")
        elif VERBOSE[0]:
            # 2026-08-06 Vic 提出「通过的项目就不用再 QA 了」。
            # **检查不删**（删了漂移会回来，见模块头注释），改成默认不打印通过项——
            # 他要解决的是刷屏，不是要减少覆盖。想看全部用 --verbose。
            print(f"  OK {name}")
    print(f"  —— {len(CHECKS) - fails - warns} 通过 / {fails} 失败 / {warns} 提醒"
          + ("" if VERBOSE[0] else "（通过项默认不列出，加 --verbose 看全部）"))
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html", nargs="*", help="报告HTML路径")
    ap.add_argument("--today", action="store_true", help="查今天的盘前+盘后")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="打印全部检查项（默认只打失败/提醒，通过的不刷屏）")
    a = ap.parse_args()
    VERBOSE[0] = a.verbose

    targets = [Path(x) for x in a.html]
    if a.today or not targets:
        day = datetime.now().strftime("%Y-%m-%d")
        for t in ("premarket", "postmarket"):
            p = ROOT / "output" / t / f"{day}-{t}.html"
            if p.exists():
                targets.append(p)
    if not targets:
        print("没有可查的报告"); return 0

    total = 0
    for h in targets:
        t = "premarket" if "premarket" in h.name else "postmarket"
        total += run(h, ROOT / "data" / "daily" / h.name.replace(".html", ".json"))
    print(f"\n{'全部通过' if not total else f'共 {total} 项未通过——格式漂了，改完重跑'}")
    return 1 if total else 0




@check("报告里的价格必须等于口径日的收盘价（2026-08-09：8/6 盘后 17 行持仓有 9 行是 8/7 的价）")
def _price_matches_cache(html, data):
    """成因不是笔误：cache universe 里没有的票要手工补价，而组装时点常常已经过了
    下一个交易日的收盘——手工拉到的是「此刻的价」，不是「口径日的收盘价」。
    这类错误 Vic 肉眼查不出来（要逐个价格去比对第二个数据源），所以必须机器查。"""
    if data is None or not data.get("date"):
        return
    day = data["date"]
    # 口径日的 cache 文件名是「次日」（收盘数据次日才归档）——按 data_date 反查更稳
    import glob
    cache = None
    for f in sorted(glob.glob(str(ROOT / "data/cache/market_*.json")), reverse=True):
        try:
            c = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        if c.get("data_date") == day:
            cache = c
            break
    if not cache:
        return          # 没有对应口径日的 cache 就查不了，不误报
    M = cache.get("metrics", {})
    bad = []
    for key in ("positions_moomoo_table", "positions_longbridge_table",
                "index_table", "sector_table"):
        tbl = data.get(key) or {}
        for r in (tbl.get("rows") or []):
            if not isinstance(r, list) or len(r) < 2:
                continue
            tk = str(r[0]).split()[0].strip()
            m = M.get(tk)
            if not m or m.get("close") is None:
                continue
            try:
                shown = float(str(r[1]).replace(",", ""))
            except ValueError:
                continue
            if abs(shown - float(m["close"])) > 0.02:
                bad.append(f"{key}:{tk} 表内 {shown} ≠ {day} 收盘 {m['close']}")
    if bad:
        return "；".join(bad[:6]) + ("" if len(bad) <= 6 else f"（共{len(bad)}处）")


SIGNAL_LIGHT_KEYS = ["bias", "bond", "dxy", "breadth", "discipline"]


@check("今日动能温度打分固定九项（2026-08-10 Vic：「今日动能打分还是你编的啊」）")
def _risk_labels_fixed(html, data):
    """标签是 Vic 的框架，不是每天自由发挥的小标题。
    7/06–7/28 稳定了 17 个交易日，7/29~8/03 之间被我逐步换成
    Breadth / 买盘质量 / Whipsaw / Concentration / 避险需求 / 持仓风控——那批全是漂移。
    正确口径见 2026-07-22 那份。"""
    if data is None or data.get("report_type") != "premarket":
        return
    items = data.get("risk_checklist") or []
    if not items:
        return
    have = [str(x.get("label", "")).strip() for x in items]
    miss = [l for l in RISK_LABELS if l not in have]
    extra = [l for l in have if l not in RISK_LABELS]
    msg = []
    if miss:
        msg.append("缺 %s" % miss)
    if extra:
        msg.append("🔴**自造标签** %s" % extra)
    if len(items) != len(RISK_LABELS):
        msg.append("共 %d 项，应为 %d 项" % (len(items), len(RISK_LABELS)))
    if msg:
        return "；".join(msg) + "——口径见 2026-07-22 那份"


@check("信号灯必须五格齐（2026-08-10 Vic：「今天盘前的信号灯好少，少了几个呢」）")
def _signal_light_full(html, data):
    """build_signal_light 只认 bias/bond/dxy/breadth 四个块 + discipline 黄卡，
    **写别的键会被静默丢掉**（8/10 我写了 'vol'，整格不见，同时漏了 breadth 和 discipline，
    渲染出来只剩 3 格）。这类错误渲染不报错、QA 原来也不查，只有 Vic 肉眼数格子才发现。"""
    if data is None or data.get("report_type") != "premarket":
        return
    sl = data.get("signal_light")
    if not sl:
        return
    missing = [k for k in SIGNAL_LIGHT_KEYS if not sl.get(k)]
    unknown = [k for k in sl if k not in SIGNAL_LIGHT_KEYS]
    msg = []
    if missing:
        msg.append("缺 %s" % missing)
    if unknown:
        msg.append("写了渲染器不认的键 %s（会被静默丢掉）" % unknown)
    if msg:
        return "；".join(msg) + "——只认 " + "/".join(SIGNAL_LIGHT_KEYS)


PHASE1_BADGE_MARKERS = ["段1", "盘前报价未取", "待段2", "段2待", "（盘后填）"]


@check("段2定稿不能残留段1的占位（2026-08-10：徽章还写着「段1 · 盘前报价未取」）")
def _no_phase1_leftover(html, data):
    """两段式的固有风险：段1 建骨架时写的占位文字，段2 忘了删就直接发出去。
    8/10 那次是徽章——报告里明明有完整盘前报价，顶部却写着「盘前报价未取」。
    只查 badges 和标题区，不查表格正文（对账清单的「（盘后填）」是正常的）。"""
    if data is None or data.get("report_type") != "premarket":
        return
    if data.get("_phase") != 2 and "watchlist_abc" not in data:
        return          # 还在段1，占位是应该的
    bad = [b.get("text", "") for b in (data.get("badges") or [])
           if any(m in b.get("text", "") for m in PHASE1_BADGE_MARKERS)]
    for f in ("title", "subtitle"):
        v = data.get(f) or ""
        if any(m in v for m in PHASE1_BADGE_MARKERS):
            bad.append(f"{f}: {v[:40]}")
    if bad:
        return "段2 定稿里还留着段1 占位：%s" % bad


# =========================================================================
# 字段集固定（2026-08-10 Vic：「我的动能打分版，你改的我都不认识了！根本不是这些啊；
# 攻守积分版只有3个？」「怎么会发生这种事情？能偏移这么大，还会乱编」）
#
# **根因**：盘前报告一直是「继承前一天的 JSON 再改」，8/10 我在草稿脚本里从零写了
# `out = {...}`。结果是对称的两个方向的静默漂移：
#   · 我没想到的字段 → **静默消失 15 个**（攻守计分板的 VIX 那条、cross_check、
#     regime_triggers、stop_proximity、defensive_basket、breadth_table…）
#   · 我想当然写的 → **静默多出来**（`scoreboard_rows` 这个字段框架里根本没有，是我造的），
#     而且我把「QQQ 收在进攻线上方」这一条升级条件擅自扩成了 QQQ+VOO+IWM 三条
#
# REPORT_SPEC 本来就是为这件事建的（Vic 8/6「把格式固定下来，不要漂移」），
# 但它的 required_fields 只列了 15 个，盘前实际 78 个——另外 63 个不在检查范围里，
# **而且完全没有「不许多出字段」这一条**。下面两条补上。
#
# 新增字段不是不允许，是**必须显式登记**：加进 PREMARKET_FIELDS 并在这里留一行注释说明来源。
# 这样「今天多了个字段」就变成一次有意的改动，而不是某个会话的副作用。
# =========================================================================

def _template_fields():
    """从 scripts/assemble_template.py 直接解析盘前字段名——**模板是唯一真源**。

    🔴 2026-08-10 Vic：「把模板修成最新的，然后以后每次用模板，格式不要再漂移了」。
    此前 PREMARKET_FIELDS 是我手抄的一份清单，模板停更在 7/31 也没人知道——
    「模板残缺 → 用它反而丢字段 → 更不用 → 更过期」这个循环就是靠这里斩断的：
    **字段清单直接从模板长出来，模板一旦漏字段，下面那条检查立刻红。**
    """
    import re
    txt = (ROOT / "scripts" / "assemble_template.py").read_text(encoding="utf-8")
    # 只取顶层字段（缩进 1~4 空格 + "key":），排除表格内部的结构键
    # {3,} 而不是 {4,}：ftd 只有三个字符，8/10 第一版就把它漏掉了
    keys = set(re.findall(r'^\s{1,4}"([a-z_0-9]{3,})":', txt, re.M))
    return (keys - TABLE_INNER_KEYS) - RETIRED_FIELDS


# 已退役的字段：模板里保留空壳作历史记录，但既不要求出现、出现也不算自造。
# futures_table/_note —— 2026-07-11 主动删除（模板里写着「已删除，留空壳」），
# 不是 7/27 那次漂移的牺牲品。**退役必须在模板里留痕，不能直接删掉字段**，
# 否则以后没人分得清「主动退役」和「漂移丢失」。
RETIRED_FIELDS = {"futures_table", "futures_note"}


# 表格/条目内部的结构键，不是报告顶层字段
TABLE_INNER_KEYS = {
    "headers", "rows", "num_cols", "row_highlights", "ma_cols", "raw_cols", "center_cols",
    "table_class", "col_widths", "badge_cols", "ticker", "price", "role", "label", "level",
    "items", "rule", "upgrade", "downgrade", "bias", "bond", "breadth", "discipline",
    "primary", "watch", "avoid", "invalidate", "condition", "type", "threshold", "current",
    "dxy", "vol",   # signal_light 的内部键
    "status", "distance_pct", "handle", "time", "summary", "note", "aligned", "grade",
    "sector", "source", "setup", "entry", "invalid", "prob", "detail", "target", "action",
    "desc", "cells",   # "title" 不能列进来——它同时是报告顶层字段
}

@check("盘前字段集 == 模板字段集（2026-08-10 Vic：「以后每次用模板，格式不要再漂移了」）")
def _premarket_field_set(html, data):
    if data is None or data.get("report_type") != "premarket":
        return
    tpl = _template_fields()
    have = {k for k in data if not k.startswith("_")}
    unknown = sorted(have - tpl)
    # 段1 草稿本来就还没有段2 字段，只查「多出来的」；段2 定稿两头都查
    is_final = data.get("_phase") == 2 or "watchlist_abc" in data
    missing = sorted(tpl - have) if is_final else []
    msg = []
    if unknown:
        msg.append("🔴**自造字段** %s——新字段必须先加进 scripts/assemble_template.py（模板是唯一真源）" % unknown)
    if missing:
        msg.append("缺 %d 个字段：%s" % (len(missing), missing))
    if msg:
        return "；".join(msg)


# 攻守计分板的六条是 Vic 的框架，不是我可以增删的。
# 8/10 我删掉了 VIX<22、把「QQQ 收在进攻线上方」扩成三条、又加了框架里没有的「月度±25%」。
# =========================================================================
# 攻守记分板的正确口径（2026-08-10 第二次修正）
#
# 🔴 我今天上午第一次「还原」时，照的是 8/7 那份——**照的是已经漂了的版本**，
#    差点把漂移写成 QA 的标准永久固化。Vic 指了 7/22，我又只照 7/22，
#    结果检查对 7/15 和 7/23 全部误报——**因为板子本来就是会长的**。
#
# 抽 7 月全月比对之后，真正不变的是**四个 type 桶**，不是某一组固定条件：
#   upgrade    进攻线 / 20MA / 10日ratio（3~4 行）      —— 全程都在
#   downgrade  T2108 / 4%下跌家数 / VIX / 周防守线（2~4 行） —— 全程都在
#   techparity SMH 解禁线 / 结构修复线（1~2 行）        —— 7/13 起
#   duration   10Y >4.50% / DXY >103 久期防线（1~2 行）  —— 7/06~7/24 一直在，
#              **8/10 我漏了整个桶**
# 行数在 7~11 之间浮动是正常的（新增久期防线、SMH 换线都会改行数）。
# 所以检查改成「骨架 + 核心条件」，允许加行，但**不允许整桶消失**。
SCOREBOARD_BUCKETS = {"upgrade", "downgrade", "techparity", "duration"}
# 四个核心条件从 7/06 起没缺过，但**写法变过**（7/13–7/20 写作「10D breadth ratio」「升级攻线」），
# 所以按同义词组匹配，不按字面。基线形态取 **7/23–7/24**（11 行 4 桶，框架成熟后的样子）；
# 7/06–7/22 会被这条标出来，那是框架还在成形，不是漂移。
SCOREBOARD_CORE = [
    ("T2108",),
    ("VIX",),
    ("10日ratio", "10Dbreadthratio", "10日比值"),
    ("进攻线", "升级攻线"),
]

# 今日动能温度打分的九个标签同样来自 7/22（7/06–7/28 稳定 17 个交易日）。
# 7/29~8/03 之间被我逐步换成 Breadth / 买盘质量 / Whipsaw / Concentration /
# 避险需求 / 持仓风控——那批全是漂移。
RISK_LABELS = [
    "S&P 500 overextension", "Increasing downward momentum", "Top range breakdown",
    "Technical deterioration", "Market breadth worsening", "VIX >20 spike",
    "利率外生冲击", "地缘外生冲击", "Theme momentum weakening",
]


@check("攻守记分板骨架固定（2026-08-10 Vic：「攻守积分版只有3个？」+「7月随机2个报告比对」）")
def _scoreboard_fixed(html, data):
    if data is None or data.get("report_type") != "premarket":
        return
    rows = data.get("scoreboard_rows") or []
    if not rows:
        # 🔴 不能 return——8/03~8/07 那批正是「这个字段整个不存在」（被拆进
        # gate_scoreboard_rows + breadth_score_rows），静默放过等于漏掉最严重的一种漂移。
        if data.get("_phase") == 2 or "watchlist_abc" in data:
            return ("**攻守记分板整块缺失**（scoreboard_rows 为空）"
                    "——是不是又被拆进 gate/breadth 两张表了？口径见 2026-07-22")
        return
    buckets = {r.get("type") for r in rows if isinstance(r, dict)}
    conds = " ".join(str(r.get("condition", "")) for r in rows if isinstance(r, dict)).replace(" ", "")
    msg = []
    lost = SCOREBOARD_BUCKETS - buckets
    if lost:
        msg.append("**整桶缺失** %s（四桶：升级/降级/技术平价/久期防线）" % sorted(lost))
    unknown = buckets - SCOREBOARD_BUCKETS
    if unknown:
        msg.append("出现未知 type %s" % sorted(unknown))
    miss_core = [grp[0] for grp in SCOREBOARD_CORE
                 if not any(alt.replace(" ", "") in conds for alt in grp)]
    if miss_core:
        msg.append("缺核心条件 %s（这四条从 7/06 起没缺过）" % miss_core)
    if not (7 <= len(rows) <= 12):
        msg.append("共 %d 行，历史区间是 7~11 行" % len(rows))
    if msg:
        return "；".join(msg) + "——**允许加行，不允许整桶消失**；口径见 2026-07-22 / 07-24"


# 🔴 入口守卫必须放在文件最末。2026-08-10 发现它卡在中间，
# 结果**它后面注册的 5 条检查在 `python scripts/qa_report.py` 直跑时全部不生效**
# （经 render_report.py import 时反而是生效的——同一份代码两种行为，最难查的那种）。
# 其中包括 8/9 建的「报告里的价格必须等于口径日收盘价」——**它从建成起就没在直跑模式下跑过**。
# 以后新增 @check 一律往这行**上面**加。
if __name__ == "__main__":
    sys.exit(main())
