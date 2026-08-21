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


def _all_caches():
    import glob
    for f in sorted(glob.glob(str(ROOT / "data/cache/market_*.json")), reverse=True):
        try:
            yield json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue


def _cache_for_day(day: str):
    """按 data_date 反查 cache（文件名是「次日」，收盘数据次日才归档）。找不到返回 None。"""
    for c in _all_caches():
        if c.get("data_date") == day:
            return c
    return None


def _cache_for_report(data):
    """报告的**口径 cache**。盘前/盘后的口径日不是同一天，这里统一解析：

      · 盘后：报告日 == 口径日（当天收盘），走 data_date == date；
      · 盘前：报告写在开盘前，用的是**上一个交易日的收盘**——
        `data_date` 是报告日的前一天，`_cache_for_day(报告日)` 永远查不到。

    🔴 2026-08-19 发现：原来三条检查全走 `_cache_for_day(data["date"])`，
    于是**在盘前报告上一条都没生效过**——包括 2026-08-09 那条
    「报告里的价格必须等于口径日收盘价」。它建起来是为了盘前那次 AAOI 事故，
    却因为这个偏移，一年里只在盘后跑过。找不到返回 None（不误报）。
    """
    if not isinstance(data, dict) or not data.get("date"):
        return None
    day = data["date"]
    if data.get("report_type") == "premarket":
        # 🔴 盘前**只能**取 data_date 严格早于报告日的那份，不许先试 data_date == 报告日。
        #    T 日盘前报告写在开盘前，用的是 T-1 收盘；而「data_date == T」那份 cache
        #    是 T+1 早上生成的、装着 T 日收盘——**对盘前报告来说那是未来函数**。
        #    2026-08-19 差点写错：先 exact 再回退，8/18 的盘前报告就会去比 8/18 的收盘，
        #    凭空报出 16 行「价格不符」。（同 COMBINED breadth 那条：盘前绝不碰当日 live。）
        best = None
        for c in _all_caches():
            dd = c.get("data_date")
            if dd and dd < day and (best is None or dd > best.get("data_date")):
                best = c
        return best
    return _cache_for_day(day)


_HHMM = re.compile(r"[0-2]?[0-9]:[0-5][0-9]")
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
    # 2026-08-11 补两处同性质豁免（这条警告 8/03–8/10 每天都报、一次都没被修，
    # 查下来剩的全是"本来就该多位"的数——按 CONTEXT「加提醒然后天天忽略 = 加了条不抓东西的检查」处理）：
    # ① brier-line 那一行的 Brier 总分，跟 brier-val 是同一个理由，只是元素不同
    body = re.sub(r'<p class="brier-line">.*?</p>', "", body, flags=re.S)
    # ② 代理相对强弱表的比值/20日均值：0.9297 vs 0.9368 差 -0.75%，压到 2 位会变成两个 0.93
    body = re.sub(r"<h3>代理相对强弱.*?</table>", "", body, flags=re.S)
    # ③ 2026-08-17 补：Brier 从盘后搬到周报后（Vic：「brier score 就放周报吧」），
    #    它出现在**表格行**里、不再是 brier-line 段落，上面两条豁免都盖不到——
    #    于是这条警告会每周稳定报一次，**又变成一条天天被忽略的检查**（正是 CONTEXT 警告过的）。
    #    豁免范围严格限定为「本行文字里含 Brier」，不是所有表格行，别开成通用口子。
    body = re.sub(r"<tr>(?:(?!</tr>).)*?Brier(?:(?!</tr>).)*?</tr>", "", body, flags=re.S)
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


@check("模板占位符不许漏进正文（2026-08-21：signal_light 的 high|mid|low 直接渲染出去了）")
def _no_placeholder_leak(html, data):
    """Vic 2026-08-21 发来截图：「今日信号灯」里 BIAS 那格写着 **high|mid|low**，
    RATES / DXY / BREADTH 三格全空 —— 我只填了 signal_light.discipline，
    四个维度还留着模板里的占位字符串，**照原样渲染出去了**。

    这类事故的共同点是「填了一半」：模板给的示例值本身是合法字符串，
    不填也不会报错，只会安静地印在页面上。所以在渲染结果里直接搜这些字面量。
    """
    if not html:
        return
    body = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", body)
    marks = ["high|mid|low", "low|mid|high", "hit/miss", "TICKER 或 TICKER|account",
             "{ticker}", "YYYY-MM-DD", "xxx", "待填", "TODO"]
    hit = [m for m in marks if m in txt]
    if hit:
        return "正文里出现模板占位符：%s ——某个字段只填了一半" % " · ".join(hit)


@check("emoji 不许一种砸到底（2026-08-21 Vic：「我也喜欢emoji，只是不喜欢红绿灯，可以用各种各样的」）")
def _emoji_variety(html, data):
    """Vic 2026-08-21：「🎯这个太多了…不用一直用同一个吗」。

    当天那份盘前 142 个 emoji **只有 3 种**：🔴×97 / 🎯×38 / ⚠×7。
    同一个符号砸到底，等于没有强调 —— 跟 2026-08-18 持仓表退役整行底色、
    2026-08-19 A 级不填色是同一条：**颜色/符号只有稀有时才是信号。**

    口径（对报告 JSON 的全部文本）：
      · 总数 ≤ 90
      · 种类 ≥ 5
      · 单一 emoji 占比 ≤ 40%
    他不喜欢的是「红绿灯」（同一组三色轮着用），不是 emoji 本身 —— 所以这条查的是
    **多样性和总量**，不是禁用。
    """
    if data is None:
        return
    import collections as _c
    import re as _re
    # 🩹 2026-08-21 修：本来数的是 JSON，而 JSON 里的 🔴/⚠️ 会被 render 层的
    #    strip_lights() 剥掉、根本不渲染 —— 等于在数看不见的东西。
    #    改成数**渲染后的正文**（去掉 <style> 和标签），也就是 Vic 真正看到的那些。
    _body = _re.sub(r"<style.*?</style>", "", html, flags=_re.S)
    txt = _re.sub(r"<[^>]+>", " ", _body)
    got = _c.Counter(_re.findall(r"[🌀-🫿☀-➿]", txt))
    tot = sum(got.values())
    if tot == 0:
        return
    top, cnt = got.most_common(1)[0]
    errs = []
    if tot > 90:
        errs.append("总数 %d >90" % tot)
    if len(got) < 5:
        errs.append("只有 %d 种（要 ≥5）：%s" % (len(got), "".join(got)))
    if cnt / tot > 0.40:
        errs.append("%s 占 %.0f%%（要 ≤40%%）" % (top, cnt / tot * 100))
    if errs:
        return "；".join(errs)


@check("盘后 01 收盘总结：指数小结和板块小结必须合成一块 callout（2026-08-21 Vic 第二次指出）")
def _close_summary_merged(html, data):
    """Vic 2026-08-21：「这两个小结是应该放一起，第二次错哦」。

    指数表小结 + 板块表小结拆成上下两个蓝框，读的人要自己在两个框之间接一次。
    渲染层已改成 chr(10).join 合并，这条守着它不要漂回去。
    口径：01 节（到「软件细分」之前）里 callout 开标签只允许出现一次。
    """
    if data is None or data.get("report_type") != "postmarket":
        return
    if not (data.get("index_table_note") and data.get("sector_table_note")):
        return
    i = html.find("01 收盘总结")
    j = html.find("软件细分", i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        return
    n = html.count('<div class="callout', i, j)
    if n > 1:
        return "01 收盘总结里有 %d 个 callout——指数小结和板块小结要合成一块" % n


@check("盘后对账每行都要有 result（空 result 会被渲染成「未触发」，看起来像没错过）")
def _recon_result_filled(html, data):
    """🔴 2026-08-21 建，起因是当天 Vic 一眼看出来的事故。

    盘后模板用 `RESULTS.get(_claim[:12])` 做结果查表 —— **用固定 12 个字符当键**。
    中文 claim 的前 12 字长度全看写法（"**XBI 今日收盘守"=11、"**T2108 今日收回 5"=14），
    键只要不是刚好 12 字就静默匹配不上，result 变成空字符串，
    **页面把它渲染成「未触发」** —— 五条里四条本该是 miss，看起来却像「没触发所以不算错」。
    Vic：「你的盘后报告不是4条都失误嘛…写了未触发…做trader就不能怕错」。

    键匹配已改成前缀匹配，但**匹配逻辑还会再变，空 result 这个症状要有人守**。
    """
    if data is None or data.get("report_type") != "postmarket":
        return
    rows = data.get("recon_rows") or []
    if not rows:
        return
    blank = [r.get("plan", "")[:24] for r in rows if not (r.get("result") or "").strip()]
    if not blank:
        return
    return ("%d/%d 条对账没有 result（会渲染成「未触发」）：%s"
            % (len(blank), len(rows), " · ".join(blank[:3])))


@check("盘后必须报 Brier 而不只是命中率（送分题堆出来的「满分日」要能被看穿）")
def _recon_brier(html, data):
    if data is None or not data.get("recon_rows"):
        return
    st = helpers.brier_score(data["recon_rows"])
    if st.get("no_prob"):
        return f"{st['no_prob']}条已判定的对账行没有prob，Brier算不全"
    if st.get("brier") is None:
        return "recon_rows全部无法评分（既没prob也没result）"
    # 🔴 2026-08-17 改：不再要求**盘后**渲染 Brier 行（Vic：「brier score 就放周报吧」）。
    #    但这条检查的初衷——「送分题堆出来的满分日要能被看穿」——不能跟着一起消失。
    #    改成守住上游：每条已判定的行必须有 prob（上面已查），且概率口径必须写出来。
    #    判语本身留给周报，那里 n 够大。
    if not (data.get("recon_prob_note") or "").strip():
        return ("Brier 算得出来，但 recon_prob_note 是空的——"
                "**单日不印 Brier 数字可以，概率口径不能不写**，"
                "否则没人能看穿送分题堆出来的满分日")


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
    # 🔴 2026-08-19：index_table 改成七只指数面板（list[dict]），不再是 {"rows":[[...]]}。
    #    两种形状都要认，否则检查本身抛异常 —— 而**抛异常的检查等于没有检查**。
    def _tk(r):
        if isinstance(r, dict):
            return r.get("ticker", "")
        return r[0] if isinstance(r, (list, tuple)) and r else ""

    for field in ("atr_extension_table", "index_table"):
        v = data.get(field)
        rows = v.get("rows") if isinstance(v, dict) else v
        if not rows:
            continue
        got = [str(_tk(r)).split()[0] for r in rows]
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
    # 🔴 2026-08-20：四件套标签在渲染时会被 build_note_callouts 改写——
    #    「【强势/可持有】XLV」变成「强势/可持有：XLV」（剥掉【】、补上：）。
    #    探针若原样比对就会误报「整块没渲染」，而内容其实在。
    #    **两边都把【】：等分隔记号一起去掉**，只比实字。
    _NOISE = r"[*#`\s【】：:·、（）()]|🔴|🟢|⚠️|🎯|⭐|️"
    plain = re.sub(_NOISE, "", _htmlmod.unescape(_text(html)))

    def _probe(s):
        s = _htmlmod.unescape(str(s))
        s = re.sub(_NOISE, "", s)
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
        # 🔴 2026-08-19 Vic：「三个角度分歧：闸门位置=中性、市宽打分=偏空、动能打分=偏空
        #    既然这样 闸门位置提到市宽上面」——build_cross_check 挂在「市宽打分」末尾、
        #    点名三个角度，而闸门原本排在第 7 位，读到那句结论时还有一个角度没出现过。
        #    渲染侧的顺序常量在 render_report.PREMARKET_SECTION_ORDER，两边要同步改。
        "sections": ["signal", "gate", "risk", "breadthscore", "macro",
                     "positions", "news", "setup", "wrapup", "scenario"],   # 2026-08-21：情景＋对账台账合并成最后一节
        "optional": ["ftd", "bounce"],          # FTD 2026-08-06 起暂停；反弹品类等 Vic 指令
        "required_fields": ["signal_light", "risk_checklist", "gate_scoreboard_rows",
                            "breadth_score_rows", "sector_rs_tables", "unilateral_scan_table",
                            # etf_table 2026-08-17 退役，读数并进 gate_scoreboard_rows（已是必填）
                            "positions_moomoo_table", "positions_longbridge_table",
                            "strong_sector_setups_table", "watchlist_abc", "playbook_scenarios",
                            "key_takeaways", "today_position", "recon_ledger"],
        # 2026-08-12：两段式取消 → 不再有「段1 草稿可以缺这些」的豁免；
        # premarket_movers 整块退役（已在 RETIRED_FIELDS）。
        "phase1_exempt": [],
    },
    "postmarket": {
        # 🔴 2026-08-20 Vic：「这个改成和盘前报告一样的闸门格式吧？有颜色容易看」——
        #    开头的收盘四张卡换成闸门表，节 id = closegate（不能叫 close，
        #    后面「01 收盘总结」已经占了那个 id）。
        "sections": ["closegate", "recon", "hitrate", "lessons", "newswatch", "close", "breadth",
                     "setupa", "xwatch", "earnings", "positions", "outlook"],
        "optional": ["ml"],
        "required_fields": ["recon_rows", "hit_rate_stats", "iterations", "news_tracking",
                            "gate_scoreboard_rows", "index_table", "sector_table", "breadth_live_table",
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
    # 🔴 2026-08-11 Vic：「qa里面写问 有没有用builder」——**每次都要看得见答案，
    #    不是只在失败时才报**。通过项默认不打印，所以这一条单独提到抬头来：
    #    它回答的是「这份报告是怎么来的」，跟其他"格式对不对"的检查不是一类问题。
    if data is not None:
        _rt = data.get("report_type") or "?"
        # 两份模板都从 2026-08-11 起盖戳，之前的报告一律豁免（回头补戳等于伪造记录）
        _tpl, _cut = {"postmarket": ("assemble_template_postmarket.py", "2026-08-11"),
                      "premarket": ("assemble_template.py", "2026-08-11")}.get(_rt, (None, None))
        if _tpl:
            _b = data.get("_builder")
            if _b:
                print(f"  builder: 用了 —— {_b}"
                      + (f"（{data.get('_builder_at')}）" if data.get("_builder_at") else ""))
            elif _cut and (data.get("date") or "") < _cut:
                print(f"  builder: 无戳 —— {_cut} 之前没有盘后模板，豁免（不是违规）")
            else:
                print(f"  builder: **没用** —— 这份是手写的，应该从 scripts/{_tpl} 派生")
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
    cache = _cache_for_report(data)
    if not cache:
        return          # 没有对应口径日的 cache 就查不了，不误报
    M = cache.get("metrics", {})
    day = cache.get("data_date") or day      # 盘前报告日 ≠ 口径日，报错文案要写口径日
    bad = []
    # 🔴 2026-08-19：index_table 是 list[dict]（ticker/close），单独校验，
    #    它现在是七只指数在报告里的唯一出处，价格错了没有第二张表能对出来。
    for r in (data.get("index_table") or []):
        if not isinstance(r, dict):
            continue
        tk, c_ = r.get("ticker"), r.get("close")
        m = M.get(tk) or {}
        if c_ is None or m.get("close") is None:
            continue
        if abs(float(c_) - float(m["close"])) > 0.005:
            bad.append("index_table %s 写的是 %s，%s 的收盘是 %s" % (tk, c_, day, m["close"]))

    for key in ("positions_moomoo_table", "positions_longbridge_table", "sector_table"):
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


def _template_headers():
    """从模板里解析每张表声明的 headers —— 表头也归模板管（2026-08-10）。"""
    import re, json as _j
    txt = (ROOT / "scripts" / "assemble_template.py").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'"([a-z_0-9]+)":\s*\{"headers":\s*(\[[^\]]*\])', txt):
        try:
            out[m.group(1)] = _j.loads(m.group(2).replace("'", '"'))
        except Exception:
            pass
    m = re.search(r'RS_HEADERS\s*=\s*(\[[^\]]*\])', txt)
    if m:
        out["sector_rs_tables"] = _j.loads(m.group(1).replace("'", '"'))
    return out


@check("表头必须等于模板声明（2026-08-10 Vic：「直接改模板吧」——10 张表头曾各写各的）")
def _headers_match_template(html, data):
    """8/10 逐张比对发现 10 张表的表头跟模板不一致，其中单边榜整列 RS(1周) 被我换成了 RSI，
    Vic 一眼看出「rs应该没有%的吧」。表头也是口径，一样归模板管。
    模板过期的情况（例：持仓表的「盘前」列是 Vic 8/6 要求加的）**改模板不改报告**。"""
    if data is None or data.get("report_type") != "premarket":
        return
    bad = []
    for k, want in _template_headers().items():
        if k in RETIRED_FIELDS:
            continue
        v = data.get(k)
        got = (v[0].get("headers") if isinstance(v, list) and v and isinstance(v[0], dict)
               else (v.get("headers") if isinstance(v, dict) else None))
        # 2026-08-12：「盘前」列整个退役，持仓表回到模板声明的 7 列，这里不再补列。
        if got is not None and got != want:
            bad.append("%s\n       模板 %s\n       实际 %s" % (k, want, got))
    if bad:
        return (("这些表的表头跟模板不一致（%d 张）：\n     " % len(bad))
                + "\n     ".join(bad[:4]))


@check("板块表必须是模板的六列（2026-08-12：「盘前」列退役后从七列变六列）")
def _sector_rs_headers(html, data):
    """模板 RS_HEADERS = TICKER / T-1% / 5日% / 1月% / RS(1周) / **驱动·原因**。
    第 5 列注明「留空当天手写」。8/10 我写过 6 列表头配 7 列数据，错位之后那一列
    在页面上就是一片空白——Vic 一眼看出来了。
    🔴 2026-08-12「盘前」列整列退役（Vic：「盘前数字没什么用」），七列 → 六列。"""
    if data is None or data.get("report_type") != "premarket":
        return
    # 🔴 2026-08-20 Vic：「我主要看 rs，所以 rs 放驱动前面」——RS 与驱动对调
    want = ["TICKER", "T-1%", "5日%", "1月%", "RS(1周)", "驱动/原因"]
    bad = []
    for t in data.get("sector_rs_tables") or []:
        h = t.get("headers") or []
        rows = t.get("rows") or []
        if h != want:
            bad.append("%s 表头是 %s" % (t.get("title"), h))
            continue
        if rows and len(rows[0]) != len(want):
            bad.append("%s 表头%d列/数据%d列 错位" % (t.get("title"), len(want), len(rows[0])))
            continue
        blank = sum(1 for r in rows if not str(r[5]).strip())   # 驱动列 2026-08-20 起是第 6 格
        if blank == len(rows) and rows:
            bad.append("%s 的「驱动/原因」整列没写" % t.get("title"))
    if bad:
        return "；".join(bad[:4]) + "——列定义在 assemble_template.RS_HEADERS"


@check("七只指数的表必须全在 03 那一节（2026-08-19 Vic：「指数所有表位置放一起」）")
def _index_single_home(html, data):
    """VOO/QQQ/DIA/IWM/SMH/RSP/QQQE 的所有表必须都在 03 指数闸门那一节里。

    改之前它们散在三个地方：03 的闸门表、01 宏观里的「C · 指数」（距50MA ATR）、
    01 里 RS 表的「指数基准」组。**同一组 ticker 隔着好几屏画三遍**，
    读者要跨节拼才知道某只指数什么状态。

    🔴 2026-08-19 Vic 分两轮定的：先「集中到一个地方」，
    再「格式改回去，让我想想先，目前新板块没有以前得好」——
    **所以合并的是位置、不是长相**：三张旧格式的表挨着放。
    查的是渲染结果（哪一节里出现），不是数据（字段照旧都在）。
    """
    if data is None or data.get("report_type") != "premarket":
        return
    if not data.get("index_table"):
        return "盘前缺 index_table —— 七只指数的唯一出处不能空"
    bad = []
    body = html.split("</style>")[-1]
    # 🔴 2026-08-19 第二轮 Vic：「指数所有表位置放一起，但是格式改回去」——
    #    **查的不再是「只能有一张表」，而是「所有指数表都必须在 03 指数闸门那一节里」**。
    #    三张旧格式的表挨着放是允许的；散到 01 宏观里去不允许。
    import re as _re
    m = _re.search(r'<section[^>]*id="gate"[^>]*>(.*?)</section>', body, _re.S)
    if not m:
        return "找不到 03 指数闸门那一节"
    gate_html, outside = m.group(1), body[:m.start()] + body[m.end():]
    for probe, what in (("指数基准", "指数基准 RS 表"),
                        ("距50MA（ATR倍数）", "距50MA(ATR) 表"),
                        ("C · 指数", "旧的 01-C 指数表")):
        if probe in outside:
            bad.append("「%s」出现在 03 之外" % what)
    if "指数基准" not in gate_html:
        bad.append("03 里没有指数基准 RS 表")
    if bad:
        return ("；".join(bad)
                + "——七只指数的所有表都放在 03 指数闸门一节里（2026-08-19 Vic：「位置放一起」）")


@check("催化剂在手：空表必须写明四条口径逐条查过（2026-08-20 Vic：EP/burst 选不出来）")
def _catalyst_watch_explained(html, data):
    """🔴 起因：Vic 8/19 买了 PURR 和 COIN，盘前报告一只都没提示。

    实测过**为什么不能靠形态扫描**：8/18 收盘 COIN −2.87%／量比 0.91×／收区间 4%，
    PURR +0.70%／量比 1.35×／收区间 63%——**T-1 价格里没有任何爆发特征**。
    能提前抓到的只有催化剂，而 8/19 开盘前四条催化剂全都已存在
    （SEC 加密框架 / 白宫峰会 / PURR 财报窗口 / 德鲁肯米勒新建仓）。

    所以这条查的是**空表有没有被解释**：
    「今天真的四条都空」和「今天没查」在页面上长得一模一样——
    跟 Trump 那格「没看到就写没有」是同一个失败模式。
    """
    if data is None or data.get("report_type") != "premarket":
        return None
    cw = data.get("catalyst_watch")
    if cw is None:
        return "缺 catalyst_watch 字段"
    if cw.get("rows"):
        return None
    note = str(data.get("catalyst_watch_note") or "")
    if len(note) < 20:
        return ("催化剂在手是空表，但 catalyst_watch_note 没写查过什么——"
                "四条口径（财报窗口 / 13F 新建仓 / 政策·监管日程 / X 点名）"
                "要逐条说明查过且为空")
    return None


@check("Trump 那格写「无」必须写清查过什么（2026-08-19 我写「无新增」，实际当天有白宫加密峰会）")
def _trump_no_event_needs_evidence(html, data):
    """🔴 2026-08-19 的报告写了「今日无 Trump 点名个股/行业的新事件（Truth Social 侧无新增）」。

    **当天有白宫加密峰会**：Trump + SEC 主席 Atkins + CFTC 主席 Selig +
    Coinbase/Kraken/Ripple/Gemini/Chainlink/Robinhood/NYSE/Nasdaq/ICE，
    Trump 当场说 **CFTC 正在推动把 Hyperliquid 引入美国**——
    而 Vic 的持仓 PURR 就是 Hyperliquid Strategies。**PURR 当天 +30.42%。**

    根因不是漏看，是**写法**：我没有主动查 Trump，是「13 个账号的时间线里没看到，就写没有」。
    CONTEXT 写死了 Trump 是**第一优先级**且是「**一类事件监听**，不是一个 X 账号」。

    所以这条查的是：**只要 news_today 里有一条在讲 Trump 且断言「无/没有/未见」，
    它就必须同时写出查过的来源**（@账号 或 Truth Social / 白宫 / SEC / CFTC 等具体入口）。
    「没看到」和「查过没有」在页面上长得一样，**但它们不是一回事**。
    """
    if data is None or data.get("report_type") != "premarket":
        return None
    NEG = ("无", "没有", "未见", "未发现")
    SRC = ("@", "Truth Social", "白宫", "SEC", "CFTC", "WatcherGuru", "已查", "已搜")
    for item in (data.get("news_today") or []):
        t = str(item)
        if ("Trump" not in t) and ("特朗普" not in t):
            continue
        if not any(n in t for n in NEG):
            continue
        if not any(x in t for x in SRC):
            return ("Trump 那条写了「无」却没写查过哪里：%s…——"
                    "「没看到」不等于「查过没有」，把来源写出来"
                    "（@WatcherGuru / Truth Social / 白宫·SEC·CFTC 日程）" % t[:40])
    return None


@check("2026-08-20 定的格式不许漂回去（小结无标题 / 罗马数字 / 陈述用白块）")
def _format_lock_0820(html, data):
    """8/20 一天里 Vic 连提四次同类问题，全部收口在渲染层。这条守住它们。

    · 「哈哈你又有两个小结」→ callout **不再挂「小结：」标题**（默认 label="" ）
    · 「点点又来了，不如你写成 I. II. III.」→ co-item 用 upper-roman，**不用圆点**
    · 「这个不是小结，直接用白色表格吧」→ 陈述走 build_plain_block，不占蓝底
    **这三条只要有一条漂回去，页面上看着都「还行」，所以必须机器查。**
    """
    if data is None:
        return None
    body = html.split("</style>")[-1]
    css = html.split("</style>")[0]
    bad = []
    if "小结：" in body or "<span class=\"co-label\">小结</span>" in body:
        bad.append("正文又出现「小结：」标题行——label 默认值应为 \"\"")
    if "upper-roman" not in css:
        bad.append("co-item 的罗马数字序号没了")
    if 'content:"•"' in css or "content: '•'" in css:
        bad.append("圆点项目符号又回来了")
    if bad:
        return "；".join(bad) + "——这三条 2026-08-20 定，收口在 render_report/report.css"
    return None


@check("盘后开头必须是闸门表（2026-08-20 Vic：「改成和盘前报告一样的闸门格式，有颜色容易看」）")
def _postmarket_gate_head(html, data):
    """盘后原来开头是四张收盘卡（VOO/QQQ/SMH/广度），Vic 要求换成盘前那张闸门表。

    **盘前盘后同一件事就该长同一个样**（跟 8/18 持仓表统一是同一条）。
    这条查：盘后有没有 gate_scoreboard_rows、节 id 是不是 closegate、状态格有没有上色。
    """
    if data is None or data.get("report_type") != "postmarket":
        return None
    if not data.get("gate_scoreboard_rows"):
        return "盘后缺 gate_scoreboard_rows —— 开头那节应该是闸门表"
    body = html.split("</style>")[-1]
    if 'id="closegate"' not in body:
        return "盘后开头没有 closegate 那一节"
    n = sum(body.count(x) for x in ("status-met", "status-unmet", "status-triggered"))
    if n < 3:
        return "闸门表的状态格没有上色（只找到 %d 个）——颜色是这次改版的全部意义" % n
    return None


@check("A 级候选跟踪表的列（2026-08-20 定：形态/区间拆列、只在 D+5 结算）")
def _track_table_shape(html, data):
    """Vic 8/20 三条：跟全部 A 级 · 形态和 5日区间%/区间ATR 拆成三列 · 自入场% 改成只在 D+5 结算。

    **列一旦改回去，「谁最紧」就又没法跨行比了**，而页面上看不出少了什么。
    """
    if data is None or data.get("report_type") != "postmarket":
        return None
    t = data.get("setup_a_track_table") or {}
    h = t.get("headers") or []
    want = ["信号日", "TICKER", "板块", "形态", "5日区间%", "区间ATR",
            "失效", "现价", "当日%", "结算%(D+5)", "状态"]
    if h != want:
        return "跟踪表表头是 %s，应为 %s" % (h, want)
    for r in (t.get("rows") or []):
        if len(r) != len(want):
            return "跟踪表 %d 列表头配 %d 列数据——错位后整列会静默变空" % (len(want), len(r))
    return None


@check("带时刻的事件必须同时给 SGT（2026-08-20 Vic：「应该告诉我 fomc 是几点，我可以熬夜」）")
def _event_time_has_sgt(html, data):
    """8/19 那份写的是「FOMC 会议纪要 今天 14:00 ET」——**只有 ET**。

    Vic 人在 SGT，14:00 ET 是他这边**次日凌晨 02:00**；
    只写 ET 等于把「今晚要不要熬夜」这个决定藏在一次时区换算后面。
    那晚 PURR 收 +29.34%、收在区间 98%——**漏这条信息的代价是可量化的。**

    只要出现 HH:MM，同一格里就得有 SGT。转换用 report_helpers.et_sgt()，
    不要手算（夏令时会错一小时）。
    """
    if not data:
        return None
    hits = []
    tbl = data.get("macro_radar_table") or {}
    for row in (tbl.get("rows") or []):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        cell = str(row[1])
        if _HHMM.search(cell) and "SGT" not in cell:
            hits.append("宏观雷达「%s」：%s" % (str(row[0])[:18], cell))
    cal = data.get("week_calendar") or {}
    for col in (cal.get("cells") or []):
        for item in (col or []):
            txt = str(item)
            if _HHMM.search(txt) and "SGT" not in txt:
                hits.append("本周日历「%s…」" % txt[:26])
    if hits:
        return "；".join(hits[:4]) + "——带时刻就要带 SGT，用 H.et_sgt() 生成"
    return None


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


@check("信号灯维度列不能中英重复（2026-08-20 Vic：「我不喜欢中英重复」）")
def _signal_light_en_only(html, data):
    """维度列只放 BIAS / RATES / DXY / BREADTH，**不放中文**。

    这条写成检查而不是文档，是因为 8/20 之前同一类格式要求已经漂回去过三次
    （见 CONTEXT「格式漂移」那节）：渲染器改了、下次谁手改一行又加回中文，
    没有会失败的闸门就发现不了。顺带钉住 BOND→RATES 的改名。
    """
    if data is None or data.get("report_type") != "premarket":
        return
    if 'class="sig-table' not in html:
        return
    seg = html.split('class="sig-table', 1)[1].split("</table>", 1)[0]
    bad = [w for w in ("方向", "利率", "美元", "广度") if ">%s<" % w in seg]
    if bad:
        return "维度列还留着中文 %s——只放 BIAS/RATES/DXY/BREADTH" % bad
    want = [w for w in ("BIAS", "RATES", "DXY", "BREADTH") if w not in seg]
    if want:
        return "维度列缺 %s（BOND 已于 8/20 改名 RATES）" % want
    if 'class="sig-en"' in seg:
        return "sig-en 小字副标题已随中文一起退役，不该再出现"


@check("本周日历：图标分类型，重要项不能过半（2026-08-20 Vic：「不要都用箭靶」）")
def _cal_icons_typed(html, data):
    """两条一起查：

      ① 日历格里**不能出现 🎯**——重要性改由字重＋色条表达，emoji 只表类型
      ② **加粗条数不能过半**——8/20 之前周三 4 条里 4 条挂 🎯，
         等于没标（同「铺满 = 等于没标」：8/18 持仓表、8/19 A级表都栽在这上面）
    """
    if data is None or data.get("report_type") != "premarket":
        return
    if 'class="cal-table' not in html:
        return
    seg = html.split('class="cal-table', 1)[1].split("</table>", 1)[0]
    if "🎯" in seg:
        return "日历里还有 🎯——图标只表类型，重要性走 hot（字重＋左色条）"
    if 'class="cal-ic"' not in seg:
        return "日历条目缺类型图标，可能又退回统一圆点"
    # 🔴 不能用前缀 count：'class="cal-i' 也匹配图标 span 的 'class="cal-ic"'，
    #    total 会翻倍、条件永远不成立（写完这条检查当场用假数据抓到的）。
    hot = seg.count('class="cal-i hot"')
    total = seg.count('class="cal-i"') + hot
    if total >= 4 and hot * 2 > total:
        return "日历 %d 条里 %d 条标了重要（过半）——标满等于没标" % (total, hot)


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

def _template_fields(template="assemble_template.py", retired=None):
    """从模板文件直接解析字段名——**模板是唯一真源**。

    🔴 2026-08-10 Vic：「把模板修成最新的，然后以后每次用模板，格式不要再漂移了」。
    此前 PREMARKET_FIELDS 是我手抄的一份清单，模板停更在 7/31 也没人知道——
    「模板残缺 → 用它反而丢字段 → 更不用 → 更过期」这个循环就是靠这里斩断的：
    **字段清单直接从模板长出来，模板一旦漏字段，下面那条检查立刻红。**

    2026-08-11：加 template 参数，盘后模板 assemble_template_postmarket.py 共用同一套逻辑
    （Vic：「现在做 assemble_template_postmarket.py 我们以后都用builder跑」）。
    """
    import re
    txt = (ROOT / "scripts" / template).read_text(encoding="utf-8")
    # 只取顶层字段（缩进 1~4 空格 + "key":），排除表格内部的结构键
    # {3,} 而不是 {4,}：ftd 只有三个字符，8/10 第一版就把它漏掉了
    keys = set(re.findall(r'^\s{1,4}"([a-z_0-9]{3,})":', txt, re.M))
    return (keys - TABLE_INNER_KEYS) - (RETIRED_FIELDS if retired is None else retired)


# 已退役的字段：模板里保留空壳作历史记录，但既不要求出现、出现也不算自造。
# futures_table/_note —— 2026-07-11 主动删除（模板里写着「已删除，留空壳」），
# 不是 7/27 那次漂移的牺牲品。**退役必须在模板里留痕，不能直接删掉字段**，
# 否则以后没人分得清「主动退役」和「漂移丢失」。
# premarket_movers/_note —— 2026-08-12 整块退役（Vic：「我也不看盘前异动选股，关于盘前的全部删了吧」）。
#   模板里留空壳作历史记录；既不要求出现、出现也不算自造。
# other_assets_table —— 2026-08-14 Vic：「整个表格删除，我只需要小结」。
#   模板留空壳，内容改由 other_assets_note 承载（后者是必备字段，要出现在报告里）。
# scoreboard_rows/_note + breadth_table —— 2026-08-17 整块退役（Vic：「我的攻守记分板删除」
#   「广度明细可以加入市宽打分表格，2表变成一涨」）。内容分别并入 regime_triggers 和 breadth_score_rows。
# adanos_scan_table/_note —— 2026-08-17 Vic：「方法3 · Adanos Top100扫描 删除这个方法」。
# etf_table —— 2026-08-17 Vic：「03 指数闸门…没必要写两次，用闸门位置格式」，
#   七只 ETF 的读数并进 gate_scoreboard_rows（etf_table_note 仍在用，不退役）。
RETIRED_FIELDS = {"futures_table", "futures_note",
                  "premarket_movers", "premarket_movers_note",
                  "other_assets_table",
                  "scoreboard_rows", "scoreboard_note", "breadth_table",
                  "adanos_scan_table", "adanos_scan_note", "etf_table"}

# 盘后已退役 / 已暂停的字段：模板里以注释形式留空壳，既不要求出现、出现也不算自造。
# breadth_stage_table/_note —— 2026-08-11 Vic：「Weinstein 728 票全扫 用不着 stage 了，这个删除」
# breadth_history_table/_note —— 2026-07-28 Vic：「整个表格删除」
# ftd / ftd_table / ftd_note —— 2026-08-06 起 FTD 追踪暂停（park，不是退役；重启需 Vic 明确说）
# tradebook_block —— 2026-07-28 Vic：「删除这个部分，你每次自己可以直接输入到tradebook」
# lessons / corrections —— 2026-07-28 并入 iterations（旧字段仍能被 _iterations_from_legacy 折进去）
RETIRED_POSTMARKET_FIELDS = {
    "breadth_stage_table", "breadth_stage_note",
    "breadth_history_table", "breadth_history_note",
    "ftd", "ftd_table", "ftd_note",
    "tradebook_block", "lessons", "corrections", "positions_note",
}


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
    # 🔴 2026-08-17：退役字段要从 have 里也减掉，盘后那条一直是这么写的，盘前漏了。
    #    漏的后果在 8/17 删记分板时炸出来：8/10~8/14 五份历史报告集体报「自造字段
    #    scoreboard_rows」——**它们写的时候那字段是合法的**，退役是今天的事。
    #    退役的语义是「不要求出现、出现也不算自造」，两边都得减。
    have = {k for k in data if not k.startswith("_")} - RETIRED_FIELDS
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


@check("每张表的行长度必须等于表头列数（2026-08-11：持仓表盘前列静默空了两天）")
def _table_row_width(html, data):
    """**这条抓的是一整类事故，不是一个字段。**

    2026-08-11 实测：持仓两张表 headers 8 列、行只有 7 格——「盘前」那一列**从来没被填过**。
    机制是两个格式撞车：模板在「现价」里塞 `（盘前x%）` 后缀（2026-08-06 之前的老格式）
    **同时**表头又写了独立的「盘前」列（新格式）；而段2 的 `patch_premarket_columns()`
    幂等判据是 `if "盘前" in headers: skip`，于是它每天直接跳过，**列永远填不上**。
    8/06–8/07 是好的，8/10 手写那天起坏掉并被模板固化。

    **为什么必须靠机器查**：渲染器对短行是容错的（缺的格子直接不渲染），
    表面上看只是「盘前那一列是空的」，不会报错、不会变形——**跟「本来今天就没有盘前报价」
    长得一模一样**。这正是「零反馈回路」那一类：读者不知道它本该有值。
    """
    if data is None:
        return
    bad = []
    for k, v in data.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        hd, rows = v.get("headers"), v.get("rows")
        if not (isinstance(hd, list) and isinstance(rows, list) and hd and rows):
            continue
        for i, r in enumerate(rows):
            if isinstance(r, list) and len(r) != len(hd):
                bad.append("%s 第%d行 %d格 vs 表头 %d列" % (k, i + 1, len(r), len(hd)))
                break        # 每张表只报第一处，避免刷屏
    if bad:
        return ("；".join(bad) + "——**列数对不上时渲染器会静默少渲染一格**，"
                "看起来只是「那一列是空的」")


@check("phase 桶必须恰好覆盖盘前模板字段集（2026-08-11，同一个坑第三次）")
def _phase_buckets_cover_template(html, data):
    """**这条查的不是某一份报告，是流水线本身。**

    为什么必须有：两段式下段1 用 `keep = PHASE1|PHASE2_PATCH` 过滤、段2 只补 PHASE2_FIELDS。
    **模板里有、三个桶里都没有的字段 = 段1 丢掉、段2 不补回 → 永久消失，而报告照样渲染得出来。**
    已发生三次：8/3（ftd / 仓位治理，靠手动往 keep 里塞才保住）、8/7（事件缺口候选一个没进报告）、
    8/11（bam / dispersion / stop_proximity / special_readthrough / adanos_scan_note /
    recon_prob_note 等 11 个，是 Vic 问「用了 builder 对吗」时顺手查出来的）。

    前两次都只在注释里写了「以后新字段必须加进来」——**写了三次，漏了三次。**
    """
    import report_helpers as _H
    tpl = set(_template_fields())
    buckets = (set(_H.PHASE1_FIELDS) | set(_H.PHASE2_PATCH_FIELDS) | set(_H.PHASE2_FIELDS))
    orphan = sorted(tpl - buckets)
    extra = sorted(buckets - tpl)
    msg = []
    if orphan:
        msg.append("🔴**模板有、phase 桶没有** %s——两段式下会永久丢失，"
                   "去 report_helpers.py 归到三个桶之一" % orphan)
    if extra:
        msg.append("phase 桶有、模板没有 %s——去 assemble_template.py 补上空壳" % extra)
    if msg:
        return "；".join(msg)


@check("报告必须由 builder 生成 · 盘前盘后（2026-08-11 Vic：「qa里面写问 有没有用builder」）")
def _builder_stamp(html, data):
    """上面那条只查**字段名**——手写 out = {...} 把 46 个键抄齐了照样能过。
    这条查 `_builder` 戳：**只有真的跑 assemble_template_postmarket.py 才会有。**

    为什么必须加：盘前模板 2026-08-10 失效的三个机械原因里，
    「没有任何入口会在开工时提醒用模板」那一条，盘后一开始也没堵——
    文档写得再清楚，新会话不读到就等于没有。**戳是唯一不依赖"记得"的那道锁。**

    只对 2026-08-11（模板建成日）及之后的报告生效——之前的报告是手写的，
    回头补戳等于伪造记录（同「对账 prob 对 2026-08-08 前降级为提醒」的处理方式）。
    """
    if data is None or data.get("report_type") not in ("postmarket", "premarket"):
        return
    if (data.get("date") or "") < "2026-08-11":     # 模板盖戳之前的报告豁免
        return
    if not data.get("_builder"):
        tpl = ("assemble_template_postmarket.py" if data["report_type"] == "postmarket"
               else "assemble_template.py")
        return (f"这份 JSON 没有 `_builder` 戳 = 没走模板。\n"
                f"      改法：copy scripts\\{tpl} -> scratchpad\\，只填 ### 手写 ###。\n"
                f"      不要手写 out = {{...}}——字段名抄齐能骗过字段集检查，但骨架和口径会静默走样。")


@check("盘后字段集 == 模板字段集（2026-08-11 Vic：「我们以后都用 builder 跑」）")
def _postmarket_field_set(html, data):
    """跟盘前那条同源。**盘后此前没有模板**，靠的是「继承前一天的 JSON」——
    那条只防得住「少字段」，防不住「前一天本身就是错的」：
    `breadth_stage_table` 从 2026-07-28 起断了 12 个交易日没人发现，
    就是因为每天都在继承一份已经缺了它的 JSON。**模板 + 本检查才是闭环。**
    """
    if data is None or data.get("report_type") != "postmarket":
        return
    tpl = _template_fields("assemble_template_postmarket.py", RETIRED_POSTMARKET_FIELDS)
    have = {k for k in data if not k.startswith("_")} - RETIRED_POSTMARKET_FIELDS
    unknown = sorted(have - tpl)
    missing = sorted(tpl - have)
    msg = []
    if unknown:
        msg.append("🔴**自造字段** %s——新字段必须先加进 scripts/assemble_template_postmarket.py"
                   "（模板是唯一真源）" % unknown)
    if missing:
        msg.append("缺 %d 个字段：%s——模板里有的字段报告必须写"
                   "（真要退役请加进 RETIRED_POSTMARKET_FIELDS 并注明日期）" % (len(missing), missing))
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


# 🔴 「攻守记分板骨架固定」这条检查 2026-08-17 随记分板一起删除。
#    它守的是 scoreboard_rows 的四桶和 7~11 行——而那块已经整体退役。
#    留着只会每天红一次，变成又一条被忽略的检查（同 8/03-8/10 那条报了 45 次没人修的）。
#    **骨架没了，守卫也要走。**


# 🔴 临时检查 · 只在 2026-08-15 那一份报告上生效（2026-08-14 Vic：
#    「今天改的部分，全部写进模板，建立临时 1 天的额外 QA，追踪明天是否都改了」）
#
# **为什么要临时的**：8/14 一天改了七处口径。改动落进模板 ≠ 明天真的会生效——
# 明天是新会话，它复制模板、填手写区、渲染，中间任何一步都可能把新口径带偏
# （最典型的：又从旧报告继承一份 15 行的广度表）。这条就是**明天那一次的验收单**。
#
# **到期自动失效**：日期不匹配直接 return。不要手工删——留着当历史记录，
# 也免得「临时检查」自己变成又一条没人维护的永久规则。
# =========================================================================
# 🔴 2026-08-16 修：原本写的是 "2026-08-15"，**那天是周六，根本没有报告**——
#    这条检查建成之后一次都不会触发，等于白建。改成下一个真实交易日 8/17（周一）。
#    教训：写「明天」的日期闸门时，先确认那天是不是交易日。
@check("候选表只有 A/B 两级（2026-08-17 Vic：「c退役」）")
def _no_grade_c(html, data):
    """C 级 = 「当日忽略」，是个明说了不做的清单，对当天决定没有输入。

    退役后降级理由要落到对应模块的 note，**不是不写**——
    这条检查守的是反面：候选表里不该再出现 C。
    """
    if data is None:
        return
    bad = [x.get("ticker", "?") for x in (data.get("watchlist_abc") or [])
           if (x.get("grade", "") or "").strip()[:1].upper() not in ("A", "B")]
    if bad:
        return ("候选表里还有非 A/B 级：%s——C 级 2026-08-17 已退役，"
                "降级理由请写进对应模块的 note" % bad)


@check("盘后正文不许出现 Brier 数字（2026-08-17 Vic：「brier score 就放周报吧」）")
def _no_daily_brier(html, data):
    """守的是「注释宣布了删除、代码没跟上」这种漂移。

    8/17 第一次删时只改了注释，渲染块留着，随后 recon_prob_note 里又写满了
    Brier 数字和「比基线差」的判语——**QA 当时只查 recon_prob_note 非空，所以绿灯**。
    这条专查「盘后正文里有没有 Brier 的数字」，让同一个洞不能再从别的字段钻回来。
    周报不受影响（判语本来就该在那里出）。
    """
    if data is None or data.get("report_type") != "postmarket":
        return
    import re as _re
    body = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=_re.S)
    body = _re.sub(r"<!--.*?-->", "", body, flags=_re.S)
    text = _re.sub(r"<[^>]+>", " ", body)
    bad = _re.findall(r"Brier[^。\n]{0,20}?(\d+\.\d+)", text)
    if bad:
        return ("盘后正文出现了 Brier 数字 %s——**日频 Brier 已于 2026-08-17 搬到周报**。"
                "recon_prob_note 只写概率口径（怎么定、为什么盘后不许改），不写分数和判语" % bad[:3])


@check("小结里的分组小标题不带项目符号（2026-08-18 Vic：「还是有小点」）")
def _co_head_no_bullet(html, data):
    """「今晚要动的：」这种冒号结尾的短行是分组标题，不是条目。

    带上项目符号后读起来像一个漏了内容的空条目——Vic 圈出来两次。
    渲染层按「≤24 字且以：结尾」自动打 co-head；这条检查守它别退化回去。
    """
    import re as _re
    bad = []
    for m in _re.finditer(r'<div class="co-item">(.*?)</div>', html, _re.S):
        txt = _re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if txt.endswith("：") and len(txt) <= 24:
            bad.append(txt)
    if bad:
        return ("这些分组小标题还挂着项目符号：%s——"
                "渲染层应给它们 class=\"co-item co-head\"" % bad[:3])


@check("盘前盘后的持仓表必须同一套列（2026-08-18 Vic：「今天改的格式固定下来」）")
def _positions_same_shape(html, data):
    """同一张表在两份报告里两个长相，就是下一次漂移的起点。

    8/17 那批格式问题（记分板 30 种写法、etf_table 和闸门表画两遍、广度两张表）
    全是「同一件事有两个地方可以写」造成的。持仓表的列由 H.POS_HEADERS_V2 定义一处，
    盘前只把最后一列改名成「论点检查 / 今日行动」（盘前问的是明天做什么，盘后问的是今天发生了什么）。
    """
    if data is None:
        return
    import sys as _s
    _s.path.insert(0, str(ROOT / "scripts"))
    import report_helpers as _H
    want = list(_H.POS_HEADERS_V2)
    for k in ("positions_moomoo_table", "positions_longbridge_table"):
        got = (data.get(k) or {}).get("headers")
        if not got:
            continue
        if got[:-1] != want[:-1]:
            return ("%s 的列和 H.POS_HEADERS_V2 不一致：%s ≠ %s——"
                    "列定义只有一处真源，改列请改 report_helpers" % (k, got[:-1], want[:-1]))


@check("持仓表不带整行底色（2026-08-18 Vic：「颜色都删除，基本都上色了」）")
def _positions_no_row_colors(html, data):
    """守的不是审美，是**信号密度**。

    8/18 实测 16 笔里 13 笔上色，只剩 3 笔白的——颜色铺满就不再是颜色。
    根因是拿「今天要动手」染色，而 p14 每天都会判出动作，它注定高频。
    替代品是 ADR% 和「距止损 X ATR」两列数字（可比、可排序、不因条数多失效）。
    """
    if data is None:
        return
    bad = [k for k in ("positions_moomoo_table", "positions_longbridge_table")
           if any((data.get(k) or {}).get("row_highlights") or [])]
    if bad:
        return ("%s 又带上了整行底色——2026-08-18 已退役。"
                "要表达紧迫程度请用「距止损 X ATR」那一列，别再加颜色" % bad)


TEMP_CHECK_DAY = "2026-08-17"

# 8/14 把单边榜票池收成纯 ETF 后，这 12 只个股不该再出现在「单边板块」榜里
_OPTICAL_STOCKS = {"AVGO", "ANET", "CRDO", "GLW", "MTSI", "FN",
                   "LITE", "MRVL", "CIEN", "COHR", "AAOI", "POET"}


@check("【临时·仅 2026-08-17】8/14 那批口径改动今天有没有真的生效")
def _temp_20260815_carryover(html, data):
    if data is None or data.get("date") != TEMP_CHECK_DAY:
        return
    bad = []
    rt = data.get("report_type")

    if rt == "premarket":
        # ① 市宽 checklist 必须是 9 项，且不含已退役的 Sheet 六项
        # 🔴 2026-08-17：数据源从 breadth_table 换成 breadth_score_rows——
        #    那天两表合一，明细行搬进了打分表（Vic：「2表变成一涨」），
        #    再照着 breadth_table 数就永远是 0 项，这条会天天误报。
        rows = data.get("breadth_score_rows") or []
        if len(rows) != 9:
            bad.append("市宽 checklist 是 %d 项，应为 **9 项**（8/14 起只用 Stockbee）" % len(rows))
        if any(("Sheet" in str(r.get("condition", "")) or "站上20MA" in str(r.get("condition", ""))
                or "站上50MA" in str(r.get("condition", ""))) for r in rows):
            bad.append("市宽表里还有「Maket breath」Sheet 那六项——**它们 8/14 已退役**")
        # ② 其他资产：表格退役、note 必填
        if (data.get("other_assets_table") or {}).get("rows"):
            bad.append("other_assets_table 又有内容了——**8/14 已退役，只留 other_assets_note**")
        if not data.get("other_assets_note"):
            bad.append("缺 other_assets_note——「其他资产」现在只靠这一段小结")
        # ③ 持仓两列不许空（Vic：「论点检查/今日行动应该写两句的吧」）
        for key in ("positions_moomoo_table", "positions_longbridge_table"):
            for r in ((data.get(key) or {}).get("rows") or []):
                if len(r) < 7 or not str(r[5]).strip() or not str(r[6]).strip():
                    bad.append("%s 里 %s 那行的「失效条件」或「论点检查/今日行动」是空的"
                               % (key, r[0]))
                    break
        # ④ 单边**板块**榜不许出现个股
        hit = [r[1] for r in ((data.get("unilateral_scan_table") or {}).get("rows") or [])
               if len(r) > 1 and r[1] in _OPTICAL_STOCKS]
        if hit:
            bad.append("单边**板块**榜里出现个股 %s——**8/14 已把票池收成纯 ETF**" % hit)
        # ⑤ 方法4 盘前异动机会必须已消失
        if html and "方法4" in html:
            bad.append("正文里还有「方法4」——**盘前异动机会 8/14 已整块删除**")
        # ⑥ BAM 要么是图要么没有，不该退回表格
        if html and "10日涨家数" in html:
            bad.append("BAM 又渲染成表格了——**8/14 改成折线图**（build_bam_chart）")

    if rt == "postmarket":
        # ⑦ p14 持仓管理执行表必须在（8/14 接入盘后）
        pmt = data.get("position_manage_table") or {}
        if not pmt.get("rows") and not pmt.get("nodata"):
            bad.append("缺「持仓管理执行表（教材 p14）」——**8/14 接入盘后，"
                       "前置是 python scripts/position_manage.py**")

    if bad:
        return ("8/14 定的口径有 %d 处没带过来：" % len(bad)
                + "".join("\n      · " + x for x in bad))


# ==========================================================================
# 🔴 拆股/复权两条（2026-08-19 建）
#
# 起因：2026-08-18 的 cache 是不复权K线，窗口里拆过股的 6 只全线污染——
#   CRWD（07-02 四拆一）距50MA 报 -42.07% 真值 **+11.35%**、Weinstein 报 Stage 4 真值 Stage 2；
#   XLY/XLU/XLB/XLK/XLE（2025-12-05 二拆一）距52周高 报 -44~-53% 真值 -0.05~-7.91%。
# CRWD 当天在 ML Leader 名单上，而那张表印的就是「距52周高」和「距50MA」。
#
# 两条检查是**两层**，都要有：
#   ①「拆股绊线」查我们自己的标记有没有被无视——快，不联网，每天都跑；
#   ②「独立源核对」查标记本身有没有漏——慢，联网，但它是唯一能发现
#      「detect_split 和复权同时失灵」的那一层。
#      只有 ① 的话，数据源整体错了我们会全票通过。
# ==========================================================================

def _report_tickers(data) -> list:
    """从报告 JSON 里把出现过的 ticker 捞出来（各表第一列）。
    只查报告里真的印了的票——全 universe 116 只逐个联网太慢，也没必要。"""
    if not isinstance(data, dict):
        return []
    out = []

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, list) and x and isinstance(x[0], str):
                    out.append(x[0])
                elif isinstance(x, dict) and isinstance(x.get("ticker"), str):
                    out.append(x["ticker"])
                else:
                    walk(x)

    walk(data)
    seen, tks = set(), []
    for t in out:
        t = t.split()[0].strip().upper() if t.split() else ""
        # 形如 SPY / BRK.B / XLU，排除中文标题和长句
        if t and len(t) <= 6 and re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", t) and t not in seen:
            seen.add(t)
            tks.append(t)
    return tks


def _yahoo_off_52w(ticker: str, asof: str, timeout: int = 8):
    """独立源（Yahoo Chart API，见 CONTEXT.md「历史K线备用方案」）算的距52周高%。
    口径要跟 fetch_market_data.analyze() 对齐：**最近252根的最高 high**，跟最新收盘比。
    Yahoo 的 close 是拆股复权、不含分红复权——正是我们要的那个基准。
    拿不到返回 None（离线/被限流时这条检查自己失效，不制造假失败）。"""
    import urllib.request, datetime
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d"
           % ticker.replace(".", "-"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        bars = [(datetime.date.fromtimestamp(t).isoformat(), h, c)
                for t, h, c in zip(r["timestamp"], q["high"], q["close"])
                if h is not None and c is not None]
        bars = [b for b in bars if b[0] <= asof]
        if len(bars) < 60 or bars[-1][0] != asof:
            return None            # 口径日对不上就不比，避免拿昨天的高点当今天的
        hi = max(b[1] for b in bars[-252:])
        return (bars[-1][2] - hi) / hi * 100 if hi else None
    except Exception:
        return None


OFF52_TOLERANCE_PP = 10.0     # 差多少个百分点算不一致（Vic 口径：10pp）
OFF52_MAX_TICKERS = 30        # 单次最多核对多少只，别把 QA 跑成半分钟


@check("距52周高必须跟独立源对得上（2026-08-19：不复权K线让 CRWD 报 -72.91%，真值 -6.41%）")
def _off_52w_vs_independent(html, data):
    """跟 2026-08-09「价格必须等于口径日收盘」同一类——**Vic 肉眼查不出派生指标**，
    要查得逐个去比对第二个数据源，所以这里就是那第二个数据源。

    这条**故意联网**。它是唯一能抓住「我们自己的拆股检测也失灵了」的一层：
    2026-08-18 那天 cache 里 6 只全错，报告侧却没有任何字段说它错了。
    离线/限流时整条安静跳过（返回 None 的都不计入），不制造假失败。
    """
    if data is None or not data.get("date"):
        return
    day = data["date"]
    cache = _cache_for_report(data)
    if not cache:
        return
    M = cache.get("metrics", {})
    # 🔴 as-of 必须用 cache 的 data_date，不是报告日——盘前报告日是 T，口径日是 T-1，
    #    拿报告日去比 Yahoo 的最后一根永远对不上，整条会静默降级成「一只都没取到」。
    day = cache.get("data_date") or day
    tks = [t for t in _report_tickers(data) if M.get(t, {}).get("off_52w_high_pct") is not None]
    # 🔴 按 |距52周高| 从大到小排，再截断。
    #    未复权的拆股**一定**表现为「距52周高异常地深」（拆股把历史高点抬高了 N 倍），
    #    所以把跌得最狠的排前面 = 所有可疑对象都排在截断线之前，截掉的永远是最不可疑的尾巴。
    #    2026-08-19 实测：不排序时 CRWD 排在第 54 位，被 30 只的上限挡在外面**没查到**——
    #    而它正是这次事故里最严重的那一只。
    tks.sort(key=lambda t: -abs(M[t]["off_52w_high_pct"]))
    if not tks:
        return
    bad, checked = [], 0
    for t in tks[:OFF52_MAX_TICKERS]:
        y = _yahoo_off_52w(t, day)
        if y is None:
            continue
        checked += 1
        ours = M[t]["off_52w_high_pct"]
        if abs(ours - y) > OFF52_TOLERANCE_PP:
            bad.append("%s cache %+.2f%% vs 独立源 %+.2f%%（差 %.1fpp）" % (t, ours, y, abs(ours - y)))
    if not checked:
        return WARN_PREFIX + "独立源一只都没取到（离线或被限流），这条本次没生效"
    if bad:
        return ("跟独立源差 >%.0fpp 的有 %d 只：" % (OFF52_TOLERANCE_PP, len(bad))
                + "；".join(bad[:6]) + ("" if len(bad) <= 6 else "（共%d只）" % len(bad))
                + "  ← 十有八九是 cache 的 adjust_type 不是 forward，重跑 fetch_market_data.py"
                + "（已核对 %d 只）" % checked)


@check("拆股存疑的票不许印距52周高／距50MA（2026-08-19：CRWD 距50MA 报 -42%，真值 +11%）")
def _split_suspect_not_rendered(html, data):
    """fetch_market_data.detect_split() 已经把票标成 split_suspect 了，
    报告侧还是把数字印出去 = 标记白打。
    正确写法是走 report_helpers.off_52w_cell() / dist_ma50_cell()，它们会出 SPLIT_BLOCKED。"""
    if data is None or not data.get("date"):
        return
    day = data["date"]
    cache = _cache_for_report(data)
    if not cache:
        return
    suspect = {t for t, m in (cache.get("metrics") or {}).items() if m.get("split_suspect")}
    if not suspect:
        return
    blocked = helpers.SPLIT_BLOCKED
    bad = []

    def scan(container, key):
        for r in (container or []):
            cells = r if isinstance(r, list) else (list(r.values()) if isinstance(r, dict) else [])
            if not cells or not isinstance(cells[0], str):
                continue
            tk = cells[0].split()[0].strip().upper() if cells[0].split() else ""
            if tk not in suspect:
                continue
            # 这一行里只要还有百分比/×ATR 形态的数字，就是把被污染的列印出去了
            for c in cells[1:]:
                txt = str(c)
                if blocked in txt:
                    continue
                if re.search(r"[-+]?\d+(\.\d+)?\s*(%|×ATR)", txt):
                    bad.append("%s:%s 那行印了「%s」" % (key, tk, txt.strip()[:24]))
                    break

    for key, val in (data.items() if isinstance(data, dict) else []):
        if isinstance(val, dict) and isinstance(val.get("rows"), list):
            scan(val["rows"], key)
        elif isinstance(val, list):
            scan(val, key)
    if bad:
        return ("这些票 cache 里已标 split_suspect（%s），报告却照印数字：" % "、".join(sorted(suspect))
                + "；".join(bad[:6]) + ("" if len(bad) <= 6 else "（共%d处）" % len(bad))
                + "  ← 这两列要走 report_helpers.off_52w_cell()/dist_ma50_cell()")


# 🔴 入口守卫必须放在文件最末。2026-08-10 发现它卡在中间，
# 结果**它后面注册的 5 条检查在 `python scripts/qa_report.py` 直跑时全部不生效**
# （经 render_report.py import 时反而是生效的——同一份代码两种行为，最难查的那种）。
# 其中包括 8/9 建的「报告里的价格必须等于口径日收盘价」——**它从建成起就没在直跑模式下跑过**。
# 以后新增 @check 一律往这行**上面**加。
if __name__ == "__main__":
    sys.exit(main())
