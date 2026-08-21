#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前JSON组装模板（2026-07-13沉淀，源自Vic"沉淀吧"；2026-07-22 改两段式 → **2026-08-12 改回一次跑完**）。

用法：每天盘前把本文件复制到scratchpad改名 assemble_YYYYMMDD.py，
只改标记为 ### 手写 ### 的判断内容；骨架/格式/字段名不要动——
它们与render_report.py的期望严格对齐，改错会渲染报错。

═══════════════════════════════════════════════════════════════════════════
🔴 2026-08-10 Vic：「把模板修成最新的，然后以后每次用模板，格式不要再漂移了；
   今天吓到我，以为做的修改都没了」

**本文件是盘前报告字段集的唯一真源。** QA 的「盘前字段集 == 模板字段集」这条检查
直接解析本文件的顶层 "key": 行来生成必备清单——
  · 报告里出现模板没有的字段 → **自造字段**，红
  · 模板里有的字段报告没写   → **缺字段**，红
所以：**每新增一个字段，必须在同一次改动里加进本文件**；
      **每退役一个字段，在本文件留空壳 + 注明退役日期**（例：futures_table 2026-07-11 退役），
      不要直接删——否则以后分不清「主动退役」和「漂移丢失」。

8/10 的事故就是绕过本文件从零手写 out = {...}：攻守记分板从 11 行 4 桶塌成自造的 4 行、
动能温度打分九项标签全被换掉、15 个字段整块消失。而当时模板停更在 7/31，
「模板残缺 → 用它反而丢字段 → 更不用 → 更过期」——这个循环已由上面那条检查斩断。

**两个绝不能动的口径**（基线 = 2026-07-23~07-24）：
  攻守记分板 scoreboard_rows：四桶 upgrade / downgrade / duration / techparity 必须齐，
    行数 7~11 浮动正常，允许加行、不允许整桶消失
  动能温度打分 risk_checklist：九项标签固定，见下方注释
═══════════════════════════════════════════════════════════════════════════

🔴**2026-08-12：两段式取消，盘前数据模块整体退役。**
   Vic：「我觉得盘前数字没什么用，我也不看盘前异动选股，关于盘前的全部删了吧，
         我打算以后 3-4 点就触发盘前」
   3-4 点（SGT）在美股盘前数据可得（16:00）之前 —— 段2 唯一的机械产出就是补盘前列，
   没有盘前数据它就没有存在理由。**现在一次跑完：**

       copy scripts\\assemble_template.py  ->  scratchpad\\assemble_YYYYMMDD.py
       python assemble_YYYYMMDD.py          # 一次跑完出定稿
       python scripts\\render_report.py data\\daily\\YYYY-MM-DD-premarket.json

   随之退役的：`snap_premarket.py`、`H.patch_premarket_columns()`、
   `PHASE2_FIELDS` / `PHASE2_PATCH_FIELDS`、RS 表和持仓表的「盘前」列、
   ETF 表 T-1% 的「（盘前x%）」后缀、**Premarket Movers 整节**。
   触发它的实例：2026-08-11 用盘前弱势（XLE -0.25%）判「利多出尽」把 OIH 从 4 分降到 C，
   收盘 XLE +1.25% 是当日最强板块 —— 而「盘前经常是假的拉高出货」是我们自己写的规则。

前置（全部跑完再组装）：
  python scripts/fetch_market_data.py      # cache/market_YYYYMMDD.json（校验data_date=上一交易日）
  python scripts/fetch_earnings_calendar.py
  python scripts/scan_semis_rsi.py
  python scripts/scan_setups.py [--sectors XL?,XL?]   # cache/setups_YYYYMMDD.json

渲染器格式gotcha（2026-07-13踩过的坑，别再踩）：
  - badges 必须是 list（空也要 []），不能 None
  - subtitle 必须是 str（可 ""），不能 None
  - x_sentiment_macro 每项 = {"handle","time","summary"}（dict，不是字符串）
  - x_sentiment_stocks 每项 = {"handle","time","ticker","note","aligned"}
  - signal_light.discipline 可以是 str 或 list[str]
  - 表格类字段统一 {"headers":[...], "rows":[[...]], "num_cols":[数字列下标]}，
    RS表/oversold表可加 "row_highlights": ["bull"/"bear"/""]
  - 2026-07-21新增两种列标注（对标老师报告格式）：
    "ma_cols":[下标] — 该列内容必须是report_helpers.tri3()产出的"20▲ 50▲ 200▲"格式，
      渲染成带period标签的独立小chip，不再是旧的纯▲▲▲文本
    "raw_cols":[下标] — 该列内容是report_helpers.badge(kind,text)组装好的HTML（Beat/Miss彩色标签），
      不会被二次转义；只用在Claude自己组装好的安全HTML上，不能塞外部原始数据
"""
import json, sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
# 2026-08-11：写死绝对路径。**本文件的用法就是复制到 scratchpad 跑**，按 __file__ 推 ROOT
# 一复制就 ModuleNotFoundError，等于每天都得手改一次路径（盘后模板同批修）。
ROOT = Path(r"D:\交易为生")
sys.path.insert(0, str(ROOT / "scripts"))
import report_helpers as H

# 🔴 2026-08-12：两段式取消（Vic：「关于盘前的全部删了吧，我打算以后 3-4 点就触发盘前」）。
# 3-4 点（SGT）在美股盘前数据可得（16:00）之前，段2 唯一的机械产出就是补盘前列 —— 没有意义了。
# PHASE 变量保留但恒为 1，只为让「python assemble_YYYYMMDD.py 1」这种旧命令不报错。
PHASE = 1
DS = date.today().strftime("%Y%m%d")          # 或手动指定 "20260713"
DAY = date.today().isoformat()

cache = H.load_cache(DS)
if cache.get("data_date") == DAY:
    sys.exit(f"🔴 cache的data_date={DAY}等于报告日本身——fetch跑在美股收盘前，拿到的不是完整"
             f"收盘数据。等美股收盘（SGT 04:00后）重跑 fetch_market_data.py")
pm = {}          # 2026-08-12 起不再取盘前快照
# （原段2 的盘前快照硬闸已随两段式一起退役 2026-08-12）
setups = H.load_setups(DS)
# 2026-07-16 Vic："以后持仓，只扫描我的tradebook"——不再读data/positions.json/查LongBridge MCP
# /比对moomoo CSV，直接从Vic自己维护的data/tradebook.json派生当前持仓（见H.load_tradebook_positions
# 文档字符串）。已知代价：tradebook里没录的仓位不会出现，Vic要自己保证及时录入。
positions = H.load_tradebook_positions()
M = cache["metrics"]

def pmp(tk, default="-"):
    """退役 2026-08-12：恒返回 default。保留函数是为了旧脚本不报 NameError。"""
    return default

# ---------- RS三组（ticker列表沿用上一份报告，机械填充+判断列手写） ----------
# 2026-07-15 Vic改版列：T-1% / 5日% / 1月% / 盘前 / 驱动 / RS(1周)——表头固定在这里，不再继承旧报告
# （当天先试了RS(1日/5日)双值格式，Vic当天纠正"只看一周的，说过了"——全报告RS统一单值1周）
# 🔴 RS = 对 QQQ 的 1 周(5日)超额收益，单位是**百分点，不带 %**（Vic 2026-08-10：
#    「rs应该没有%的吧」）。H.rs_num() 输出 "+2.1" / "-1.6" 这种形式，不要自己加 %。
#    第 6 列「驱动/原因」**留空当天手写**，整列空着会被 QA 打红。
# 🔴 2026-08-12：「盘前」列删除（Vic：「盘前数字没什么用」）。六列。
# 🔴 2026-08-20 Vic：「我主要看 rs，所以 rs 放驱动前面」
RS_HEADERS = ["TICKER", "T-1%", "5日%", "1月%", "RS(1周)", "驱动/原因"]
# 🔴 2026-08-11 修：原写法 glob("*-premarket.json") 直接取 [-1]。data/daily 里有一个
#    `sample-premarket.json`（2026-07-04 样板），字典序 's' > '2' —— **它永远排最后，
#    等于每天都拿这个样板当「上一份报告」**。后果：RS 表塌成 3 组每组 1 只
#    （XLF / SMH / XBI）、defensive_basket 变空表，**而报告照样渲染得出来**。
#    改成只认 `YYYY-MM-DD-` 开头的文件名，并排除今天自己的草稿。
_prevs = [p for p in (ROOT / "data/daily").glob("????-??-??-premarket.json")
          if p.name[:10] != DAY]
if not _prevs:
    sys.exit("🔴 找不到上一份盘前报告，RS 分组/防御篮子无法继承")
prev = sorted(_prevs)[-1]
print(f"继承 RS 分组/防御篮子 ← {prev.name}")
prev_json = json.load(open(prev, encoding="utf-8"))
rs_tables = []
for grp in prev_json["sector_rs_tables"]:
    # 🔴 2026-08-19 第二轮：「指数所有表位置放一起，但是格式改回去」——
    #    「指数基准」组**留在数据里**，只是渲染位置搬到 03 指数闸门那一节，
    #    不在 01 宏观里画。渲染侧：render_premarket 的 01 循环跳过它、03 显式渲染。
    tickers = [r[0] for r in grp["rows"]]
    rows = H.sector_rs_rows(cache, tickers)
    hl = []
    for r in rows:
        r[5] = ""  ### 手写：驱动/原因列（只给有信息量的行写） ###
        hl.append("")
    # 🔴 2026-08-17 Vic：「明明有足够位置，为什么要换行」——此前这张表没有 col_widths，
    #    浏览器自动布局把宽度均摊给五个数字列，「驱动/原因」只剩三成宽度就开始折行，
    #    右边还空着一大片。给死列宽：数字列够放 "+xx.xx%" 即可，其余全给文字列。
    rs_tables.append({"title": grp["title"], "headers": RS_HEADERS, "rows": rows,
                      "num_cols": [1, 2, 3, 4], "row_highlights": hl,
                      "table_class": "fixed-cols",
                      "col_widths": ["10%", "9%", "9%", "9%", "9%", "54%"]})

uni_rows, uni_hl = H.unilateral_rows(cache)      # hl: 距50MA≥5×ATR的行自动红底
# 前 3 名 + 去掉第 5 格「通过项」（2026-08-17 Vic）
uni_rows = [r[:4] + r[5:] for r in uni_rows[:3]]
uni_hl = uni_hl[:3]
# 2026-07-15 Vic："反弹观察区删除吧，没用"——F节已退役，不再调用H.oversold_rows()

# ---------- ETF技术总表 ----------
# 🔴顺序和成员由唯一常量 H.INDEX_ORDER 决定（2026-07-28 Vic定）：
#   VOO / QQQ / DIA / IWM / SMH / RSP / QQQE —— **全报告用VOO不用SPY，不要两个都写**。
#   盘前·指数、盘前·指数基准、盘后01收盘总结三处必须一致，QA第9条会逐表比对。
#   不要在这里手写ticker列表，改顺序去改 report_helpers.INDEX_ORDER。
etf_rows = H.gate_etf_rows(cache, H.INDEX_ORDER)   # 仍算，作为写 GATE_NOTES 时的参考读数
GATE_NOTES = {}   ### 手写：闸门表逐只判断 {ticker: 文字}，七只都要写 ###
# ⚠️坑：sector_rs_rows() 内部按RS降序排，会把 INDEX_ORDER 打乱（2026-07-31 QA第9条抓到）。
#    建「指数基准」组之后必须再过一次 H.order_index_rows(rows) 重排回来。
etf_judge = {}  ### 手写：{"VOO": "判断", ...}；VOO/QQQ/IWM盘前%在snap里可能缺，用MCP值补 ###
pm_override = {}  # 退役 2026-08-12（原用于补 snap 缺失的盘前%），留空壳
for r in etf_rows:
    r[8] = etf_judge.get(r[0], "")   # 2026-08-12：不再往 T-1% 里塞「（盘前x%）」后缀

def breadth9_rows(judge=None):
    """市宽表（2026-08-17 起是唯一那张）：9 项 Stockbee 明细 + 框架阈值/状态。

    Vic 2026-08-17：「广度明细可以加入市宽打分表格，2表变成一涨」——
    此前 breadth_table（9 项明细）和 breadth_score_rows（4 条带阈值）是两张表，
    同样的数字写两遍。现在合成一张，多出「阈值 / 状态」两列。

    🔴 **只有四条有框架阈值**（据 21 份历史报告统计）：
        10日 ratio >1.35（升级）· T2108 ≥50 · 5日 ratio ≥1.0 · 跌4%+ <400（三条降级线）
    其余五项只报数不判定。
    🔴 **「涨4%+ >300」不是框架条件**——那是 Claude 2026-08-14 自己编的，
       CONTEXT 里没有，历史报告里只在 8/14 和 8/17 出现过两次。已退回成普通明细行。
       **没有出处的门槛不许再往里加。**

    judge: {指标名: 判断文字}，填最后一列。
    """
    SB = (cache.get("stockbee") or {}).get("rows") or []
    if len(SB) < 2:
        return []
    t, y = SB[0], SB[1]
    j = judge or {}

    def row(label, cur, prev, chg="", typ="", thr="", dist="", st=""):
        return {"condition": label, "type": typ, "threshold": thr or "—",
                "current": cur, "prev": prev, "chg": chg,
                "distance_pct": dist or "—", "status": st,
                "note": j.get(label, "")}

    def d(a, b, fmt="{:+.0f}"):
        return fmt.format(a - b)

    return [
        row("涨4%+ 家数", f"{t['up4']:.0f}", f"{y['up4']:.0f}", d(t["up4"], y["up4"])),
        row("跌4%+ 家数", f"{t['dn4']:.0f}", f"{y['dn4']:.0f}", d(t["dn4"], y["dn4"]),
            "downgrade", ">400 触发", f"距门槛 {(1 - t['dn4'] / 400) * 100:.0f}%",
            "triggered" if t["dn4"] > 400 else "safe"),
        row("涨跌4%+ 比值", f"{t['up4'] / t['dn4']:.2f}:1", f"{y['up4'] / y['dn4']:.2f}:1",
            f"{t['up4'] / t['dn4'] - y['up4'] / y['dn4']:+.2f}"),
        row("5日 ratio", f"{t['ratio5']:.2f}", f"{y['ratio5']:.2f}",
            d(t["ratio5"], y["ratio5"], "{:+.2f}"),
            "downgrade", "<1.0 触发", f"缓冲 +{(t['ratio5'] / 1.0 - 1) * 100:.0f}%",
            "triggered" if t["ratio5"] < 1.0 else "safe"),
        row("10日 ratio", f"{t['ratio10']:.2f}", f"{y['ratio10']:.2f}",
            d(t["ratio10"], y["ratio10"], "{:+.2f}"),
            "upgrade", ">1.35", f"+{(t['ratio10'] / 1.35 - 1) * 100:.0f}%",
            "met" if t["ratio10"] > 1.35 else "unmet"),
        row("T2108", f"{t['t2108']:.2f}", f"{y['t2108']:.2f}",
            d(t["t2108"], y["t2108"], "{:+.2f}"),
            "downgrade", "<50 触发", f"缓冲 +{(t['t2108'] / 50 - 1) * 100:.1f}%",
            "triggered" if t["t2108"] < 50 else "safe"),
        row("季度 ↑25% / ↓25%", f"{t['q_up25']:.0f} / {t['q_dn25']:.0f}",
            f"{y['q_up25']:.0f} / {y['q_dn25']:.0f}",
            f"{t['q_up25'] / t['q_dn25'] - y['q_up25'] / y['q_dn25']:+.2f}"),
        row("月度 ↑25% / ↓25%", f"{t['m_up25']:.0f} / {t['m_dn25']:.0f}",
            f"{y['m_up25']:.0f} / {y['m_dn25']:.0f}",
            f"{t['m_up25'] / t['m_dn25'] - y['m_up25'] / y['m_dn25']:+.2f}"),
        row("月度 ↑50% / ↓50%", f"{t['m_up50']:.0f} / {t['m_dn50']:.0f}",
            f"{y['m_up50']:.0f} / {y['m_dn50']:.0f}",
            f"{t['m_up50'] / t['m_dn50'] - y['m_up50'] / y['m_dn50']:+.2f}"),
    ]


# ---------- 持仓表 ----------
# 🔴 2026-08-18 起盘前盘后用**同一套**持仓表（Vic：「今天改的格式固定下来」）：
#    TICKER / 现价 / ADR% / 距止损(ATR) / 持有理由 / 失效条件 / 论点检查·今日行动
#    同一张表两个长相就是下一次漂移的起点——8/17 那批格式问题全是这么来的。
# 🔴 **整行底色 2026-08-18 退役**（Vic：「颜色都删除，基本都上色了，还是不要了」）。
#    实测：8/18 那份 16 笔里 **13 笔上了色**（黄 10 / 红 3），只剩 3 笔白的。
#    **颜色只有在稀有时才是信号**——铺满之后眼睛看到的是一片彩色，等于没标。
#    根因是把「今天要动手」做成了颜色，**而它在这套流程里本来就是常态**：
#    p14 每天都会判出 peel / 移止损 / 退出，注定铺满。用必然高频的状态染色，从一开始就不成立。
#    **替代它的是数字**：`ADR%` 和 `距止损 X ATR` 两列本来就承担了颜色想说的事，
#    可比、可排序、不会因为条数多而失效。**不要再给这张表加 row_highlights。**
# 🔴 2026-08-14 Vic：「我的持仓里面，论点检查/今日行动应该写两句的吧」——
#    在此之前这两列**每天 20 笔全是空的**，QA 抓不到是因为它只校验列数不校验内容。
#    现在改成 {ticker: (失效条件, 论点检查/今日行动)}，**两个都必填、后者写两句**：
#      第一句 = 论点还成不成立（给证据，不是复述持有理由）
#      第二句 = 今天做什么（无动作也要写「无动作」，别留白）
#    同一只票两个账户各一笔时，key 用 "TICKER|account" 精确指定。
#    缺 key 会直接抛 KeyError——**宁可组装失败，也不要再出一份两列全空的持仓表。**
POS_JUDGE = {}  ### 手写：{"TICKER" 或 "TICKER|account": ("失效条件", "论点检查/今日行动")} ###
_mm = [p for p in positions if p["account"] == "moomoo"]
_lb = [p for p in positions if p["account"] == "longbridge"]
mm_rows, _ = H.positions_rows_v2(_mm, cache, POS_JUDGE)
lb_rows, _ = H.positions_rows_v2(_lb, cache, POS_JUDGE)
# 🔴 2026-08-20 加了「距止盈」列后，「当日表现/判断」从下标 6 挪到 7。
#    这种下标校验最容易在加列时被漏掉——漏了就等于这道闸门静默失效。
_blank = [r[0] for r in (mm_rows + lb_rows) if not r[7]]
if _blank:
    raise KeyError("持仓 %s 没写失效条件/论点检查——这两列不许留空（2026-08-14 Vic）" % _blank)


# 🔴 fill_positions 那条旧写法 2026-08-18 退役：持仓表统一走 H.positions_rows_v2。
#    旧函数按下标 5/6 回填，和新表的 7 列对不上。
#    **留着一条能漂回去的路，就一定会漂回去**——所以直接删，不留兼容分支。
#    （这段原来还写着「它同时返回行和整行底色」——底色当天晚些也退役了，
#      注释没跟上就是漂移的下一个起点，一并改掉。）

# ---------- 防御篮子（2026-07-17起：ML Leader停用，Vic重新找leader中，见CONTEXT.md
# 「ML Market Leader名单」节——不再生成ml_rows，out字典也不再填ml_leaders/ml_leaders_note/
# leader_vs_defensive_note，render_report.py已改为这些字段缺失/空时不渲染方法1的Leader部分，
# 只留防御篮子表。Vic给新名单后，把ml_list换成新名单、照旧法生成ml_rows即可复原） ----------
# 🔴 2026-08-17 Vic：「盘前列删除，但是 t-1 收盘你为什么不填」——
#    T-1 收盘% 从 2026-07-21 加进这张表起就没接过数据源，天天渲染成 "-"。
#    它和 price 来自同一个 M[ticker]，**取不到才是意外**。pct（盘前）整个不再产出。
def_rows = [{"ticker": r["ticker"],
             "price": str((M.get(r["ticker"]) or {}).get("close", "-")),
             "t1_pct": H.fpct((M.get(r["ticker"]) or {}).get("t1_pct")),
             "role": "防御篮子"} for r in prev_json["defensive_basket"]]

# ---------- 方法2 setup扫描表（机器初筛→人眼过滤后展示） ----------
# 🔴 2026-08-17 Vic：「我只要5个，评分里面最强6个，评分1-5列窄一点哦，而且你没写」——
#    此前这张表把机器扫出来的**全部** setup 原样倒出来（8/17 是 18 行，其中 15 行是能源股
#    同一个赌注），评分列 18 行全空。**没有评分的全量列表 = 没做过筛选。**
#    现在：评分必填（H.require_setup_scores 会在评分为空时直接抛错），
#    按评分降序只留最强的 6 个，评分列固定窄列宽。
# 2026-07-15 Vic改版：已按板块强弱排序（强势板块在前）、RS取代RSI、评分列1-5手写、
# 仓位/许可不再逐行占列（统一写在表后的strong_sector_setups_permission提醒里）
scan_rows_all = H.setup_scan_rows(setups, cache)

def rs_of(r):  # r[3]="+3.4"（RS单值，2026-07-15起不再是1日/5日双值）
    try:
        return float(r[3])
    except ValueError:
        return -999

focus = []  ### 手写过滤逻辑：RS>0 或 多标签共振，且属当日方向板块 ###
for r in scan_rows_all:
    # 🔴 2026-08-20 修：原条件是 r[2].count("+") >= 1，用「加号」判多标签共振。
    #    同一天我把标签连接符从 "+" 改成 " · "（因为新名字 "shakeout+burst" 自带加号），
    #    这条分支当场变成**恒假**——实测命中 0 行，71 个多标签 setup 全部没进候选池，
    #    当天的表只剩 RS>0 这一条腿在筛。**改连接符时没回头查谁在依赖它。**
    if rs_of(r) > 0 or " · " in r[2]:
        focus.append(r)
strong_scores = {}  ### 手写：{"TICKER": "4", ...} 每行1-5打分（结构质量+板块方向+延伸度+催化共振） ###
# 2026-08-20 Vic：「列的长度分布非常不合理」+「我不需要这种中文解释，我不是新手哦，
# 所以列可以合理重新排下」——RS/9EMA/量比 原来挤在一个字符串列里（最长的一列反而最窄），
# 现在拆成三个数字列；Setup 提到第 2 列；说明列只留数字（中文前缀已在 scan_setups 去掉）。
strong_rows = [[r[0], r[2], r[1] if r[1] != "-" else "watchlist",
                r[3], r[4], H.setup_vol_short(r[6]), H.setup_struct_short(r[7]),
                strong_scores.get(r[0], "")] for r in focus[:18]]

# 方法5 的输入（见下方 x_sentiment_* 注释）
_X_MACRO, _X_STOCK, _X_NOTE = H.x_from_xdesk(DAY)
print("方法5 · xdesk 提取：宏观 %d 条 / 个股 %d 条" % (len(_X_MACRO), len(_X_STOCK)))

out = {
 "report_type": "premarket",
 "date": DAY,
 "generated_at": "",  ### 手写：时间+数据口径说明 ###
 "title": "",  ### 手写 ###
 "subtitle": "",          # 必须str不能None
 "badges": [],            # 必须list不能None
 "signal_light": {
   "bias": {"level": "high|mid|low", "label": ""},
   "bond": {"level": "", "label": ""},
   "dxy": {"level": "", "label": ""},
   "breadth": {"level": "", "label": ""},
   "discipline": [],  ### 手写：核心纪律1-3条 ###
 },
 # 🔴 **攻守记分板 2026-08-17 整块退役**（Vic：「我的攻守记分板删除」）——
 #    内容和闸门位置/市宽/其他资产三处重复（最后一份 11 行里 10 行在别处已有），
 #    条件名一直在换（21 份报告 30 种写法），行数 7~12 从没固定。
 #    **它唯一的功能「升级 N/M 的聚合判断」交给 regime_triggers。**
 #    留空壳不删字段：区分「主动退役」和「漂移丢失」。
 "risk_checklist": [
   # 9项固定：S&P 500 overextension / Increasing downward momentum / Top range breakdown /
   # Technical deterioration / Market breadth worsening / VIX >20 spike / 利率外生冲击 / 地缘外生冲击 / Theme momentum weakening
   # {"label":"", "level":"low|mid|high", "detail":""}
 ],
 "risk_checklist_note": "",
 "regime_triggers": {"upgrade": {"rule": "", "items": []}, "downgrade": {"rule": "", "items": []}},
 # 🔴 2026-08-14 Vic：「以后只用 stockbee，其他删除」——**checklist 从 15 项减到 9 项**，
 #    而且**全部机械生成**（原来 15 行的数字是手抄的，每天 30 个数字都是一次出错机会）。
 #    退役的 ①-⑥ 来自 Vic 自建 Sheet「Maket breath」tab（手工 EOD 更新，停在 8/11）；
 #    老师那张「S&P 500 LIVE MARKET BREADTH」自 7/29 起 HTTP 400。两者已在
 #    fetch_market_data.py 退役成空壳。**现在单一数据源，不再有「今天哪个源能用」这个判断。**
 #    只有「判断」列手写（下标 3）——整列空着会被 QA 打红。
 # 🔴 **广度明细 2026-08-17 并进市宽打分表**（Vic：「广度明细可以加入市宽打分表格，
 #    2表变成一涨」）——9 项 Stockbee 明细现在由 breadth_score_rows 一张表承载，
 #    多出「阈值 / 状态」两列。本字段留空壳。
 # 🔴 「D · 其他资产」表格 2026-08-14 整块退役（Vic：「整个表格删除，我只需要小结」）。
 #    留空壳作历史记录，**不要往里写内容**——渲染器已不再渲染它。
 #    原来七行（10Y / VIX / DXY / 黄金 / 白银 / WTI / BTC）的数字本来也只在「信号」列被读，
 #    数字本身没人逐行看；现在把判断直接写进下面的 other_assets_note。
 "other_assets_table": {"headers": [], "rows": [], "num_cols": []},   # 退役 2026-08-14
 # 手写：一段小结，覆盖 10Y / VIX（含 VIX1D 的 contango 判断）/ DXY / 金银 / 原油 / BTC。
 # 🔴 VIX1D 不单独成条（Vic 2026-08-10：「vix1d说过去掉了」），只作为 VIX 那句的佐证。
 "other_assets_note": "",   ### 手写 ###
 "joint_signal_lines": [],  ### 手写：联合信号+覆盖指令检查 ###
 # 🔴 2026-08-20 Vic：「昨天其实你应该告诉我 fomc 是几点，我可以熬夜看下 minutes
 #    就能再买 purr 了」——**带时刻的事件必须同时给 SGT**。
 #    用 H.et_sgt("2026-08-19", "14:00") 生成，别手算时区（夏令时会算错）。
 #    ET 仍是主口径（2026-07-11 那条没被推翻），SGT 是附加不是替换。
 "macro_radar_table": {"headers": ["事件", "时间（ET · SGT）", "预期/前值", "结果/现状", "市场解读"], "rows": []},
 "macro_radar_detail": "",  ### 外部校对只认AP/IBD/MarketWatch+X池白名单 ###
 "sector_rs_tables": rs_tables,
 "sector_rs_note": "",
 # 🔴 2026-08-11 修：H.unilateral_rows() 产出 **10 格**（排名 / TICKER / 得分 / **阶段** /
 #    通过项 / 5日% / 1月% / RS / 距50MA / 延伸档位），而模板表头此前只写了 9 列——
 #    **「阶段」那一列被静默丢掉**。它不是 Vic 8/10 删掉的那个 Weinstein 独立小节，
 #    而是单边榜的 stage 过滤依据：8/11 那天 XSW / KWEB 原始得分 4/4 全场最高却落榜，
 #    正是因为 stage 3/4，不显示这一列根本看不出来为什么。
 # 🔴 2026-08-17 Vic：「我只要前3了，通过项这列删除，能短一点，我肉眼会看」——
 #    「通过项」四条每行一模一样（跌天数≤4·低点未破坏·站稳20MA·RSI强势+MA上翘），
 #    它就是「得分 4/4」的展开写法，同一件事占了整张表最宽的一列。
 "unilateral_scan_table": {"headers": ["排名", "TICKER", "得分", "阶段", "5日%", "1月%", "RS(1周)", "距50MA", "延伸档位"],
                           "table_class": "fixed-cols",
                           "col_widths": ["6%", "9%", "7%", "14%", "9%", "9%", "9%", "11%", "26%"],
                            # 🔴 2026-08-17：删「通过项」后列序左移一位，num_cols 跟着从 [5,6,7] 改成 [4,5,6]。
                            #    忘了改的话 5日%/1月%/RS 三列会静默失去涨跌色（QA 当天就抓到了）。
                            "rows": uni_rows, "num_cols": [4, 5, 6], "row_highlights": uni_hl},
 "unilateral_scan_note": "",  ### 四件套：强势/可持有·修复/需确认·弱势/暂避·小结 ###
 "futures_table": {"headers": [], "rows": [], "num_cols": []},   # 2026-07-11已删除，留空壳
 "futures_note": "",
 # 🔴 **etf_table 2026-08-17 退役**（Vic：「03 指数闸门这个表格就和上面闸门位置放一起，
 #    没必要写两次，用闸门位置格式」）——七只 ETF 的读数并进 gate_scoreboard_rows，
 #    VOO/QQQ/IWM 是闸门行、DIA/SMH/RSP/QQQE 是参考行（kind="ref"）。
 #    etf_rows 仍然算，但只作为拼 gate 行的中间量。
 "etf_table_note": "",  ### 四件套 ###
 # 🔴 7 列。「盘前」列 2026-08-12 随盘前数据模块一起退役，不再由 patcher 插列
 "positions_moomoo_table": {"headers": H.POS_HEADERS_V2[:-1] + ["论点检查 / 今日行动"],
                             "col_widths": H.POS_WIDTHS_V2, "table_class": "fixed-cols",
                             "num_cols": [], "rows": mm_rows},
 "positions_moomoo_note": "",
 "positions_longbridge_table": {"headers": H.POS_HEADERS_V2[:-1] + ["论点检查 / 今日行动"],
                             "col_widths": H.POS_WIDTHS_V2, "table_class": "fixed-cols",
                             "num_cols": [], "rows": lb_rows},
 "news_today": [],   ### Trump/战争第一优先级；重大消息必须WebSearch交叉核实 ###
 "news_week": [],
 "industry_radar_table": {"headers": ["主题", "信号", "解读"], "rows": [], "num_cols": []},
 # 🔴 2026-08-12 整块退役（Vic：「我也不看盘前异动选股」）。留空壳作历史记录，
 # 已加进 qa_report.RETIRED_FIELDS：既不要求出现、出现也不算自造字段。
 "premarket_movers": [   # 退役 2026-08-12
   # {"ticker":"", "price":"", "pct":"", "pm_vol":"", "vol_tag":"", "catalyst":"", "sector_readthrough":"", "judgment":""}
   # 全watchlist+ETF holdings |盘前|>=7%（snap_premarket.py已按此打MOVER标+算好vol20/vol_ratio_pm）
   # pm_vol/vol_tag 用 H.pm_volume_cell(pm, ticker) 取（2026-07-15 Vic要求区分放量/低量）
 ],
 "premarket_movers_note": "",
 # 🔴 **ML Leader 2026-08-17 恢复启用**（Vic：「leader 我早就启用了」）。
 #    7/17 停用 → 7/31「请加回去」→ 8/17「加 crwd panw nbis」，**两次都在扩名单**，
 #    而模板和报告里的「停用」措辞一直没跟着改。身份按 7/31 定的：看修复，不看谁最强。
 #    ml_leaders（卡片格式）留空壳作旧格式兼容，实际走 ml_leaders_table。
 "ml_leaders": [],
 "ml_leaders_table": {"headers": ["TICKER", "收盘", "T-1%", "5日%", "距9EMA",
                                  "距50MA", "RSI", "收盘区间%", "距52周高", "读数"],
                      "rows": [], "num_cols": [1, 2, 3]},   ### 手写：逐只读数 ###  # 2026-07-17起停用，留空list（渲染层遇空自动跳过Leader部分），见上方防御篮子注释
 "ml_leaders_note": "",
 "defensive_basket": def_rows,
 "leader_vs_defensive_note": "",  ### 手写：Leader vs 防御篮子的 risk-on/off 联合信号 ###
 # 🔴 **方法3 · Adanos Top100 扫描 2026-08-17 整块退役**（Vic：「删除这个方法」）。
 # 🔴 **方法5 不再重新扫 X**（2026-08-20 Vic：「我想你直接从这里提取，
 #    因为 X 我经常重复刷，不用重复扫」）。改读 xdesk 当天落盘的
 #    data/cache/x_intraday_YYYYMMDD.json —— 同一份输入重跑结果一致，台账才可对账；
 #    重复扫等于每天换一个随机样本（X 时间线不可重放）。
 #    取不到文件时返回空 list + 一句说明，**不静默回退去扫 X**。
 "x_sentiment_macro": _X_MACRO,     # H.x_from_xdesk(DAY)
 "x_sentiment_stocks": _X_STOCK,    # 同上；aligned 列仍是手写（要和当日主线对一次）
 "x_sentiment_note": _X_NOTE,       ### 手写可追加；新点名的票记得同步进 data/x_watch.json ###
 # 方法6 · 肉眼筛选（Vic / 老师）。2026-08-20 从纯文字 list 正式改成表格字段
 #   （渲染器早就支持 vic_manual_picks_table，但模板一直只有旧的 vic_manual_picks，
 #    于是每次填表都被 QA 判成「自造字段」）。
 #   列：来源 / TICKER / 结构 / RS(1周) / 距9EMA / 触发价 / 止损 / 距止损 / 评分 / 读数
 #   🔴 触发价＝5日高点、止损＝**5日低点 − 0.5×ATR14**（框架既有口径，不另发明）；
 #      距止损 <1.0ATR 标 🔴（会被噪音打掉）、>2.5ATR 标 ⚠️（超出 A 级门槛）。
 "vic_manual_picks": [],            # 旧的纯文字格式，留作历史兼容
 "vic_manual_picks_table": {"headers": ["来源", "TICKER", "结构", "RS(1周)", "距9EMA",
                                        "触发价", "止损", "距止损", "评分", "读数"],
                            "col_widths": ["6%", "7%", "13%", "6%", "7%", "7%", "7%",
                                           "8%", "5%", "34%"],
                            "num_cols": [3, 4], "center_cols": [8], "rows": []},
 "vic_manual_picks_note": "",       ### 手写 ###
 "thirteen_dg_rows": [],
 "thirteen_dg_note": "",
 "squeeze_candidates": [],
 "squeeze_note": "",
 "strong_sector_setups_table": {"headers": H.SETUP_HEADERS,
                                  # 评分 + 只留最强 6 个（口径见 H.SETUP_SCORE_DOC，写死不每天重发明）
                                  # 2026-08-20 Vic：「列的长度分布非常不合理」——机器说明是最长的一列
                                  # 却被挤到最窄，评分只有一个数字反而占一大格。固定列宽，不让浏览器自适应。
                                "col_widths": H.SETUP_WIDTHS,
                                "center_cols": [7], "num_cols": [3, 4],
                                "rows": H.top_setups(strong_rows)},
 "strong_sector_setups_permission": "",  ### 手写：当日统一仓位/许可提醒（档位/事件纪律，全表适用，一句话） ###
 # 🔴A/B/C三级写同一个字段、同一组列（2026-07-28 Vic第三次要求统一后，
 #   watchlist_a / watchlist_b_table / watchlist_c 三个旧字段已在渲染器里**直接抛异常**）。
 #   每条：{"grade":"A|B|C", "ticker":"", "sector":"", "source":"", "setup":"",
 #          "entry":"", "invalid":"", "target":"", "note":""}
 #   A级最多5只、B级最多5只；source=CONTEXT.md「机会扫描」的方法号（"方法2"/"方法6·Vic肉眼"/"X trader"…），
 #   喂进 setup_track.json 台账（Setup A专项对账用）。
 #   要被识别成Setup A，setup字段必须显式含"Setup A"或"缩量回踩9EMA"字样。
 #   扫描永不冻结：档位只写进 permission 的许可标注，不允许空表。
# 🔴 **催化剂在手**（2026-08-20 Vic：「我买了 purr 和 coin…如果你能抓到就能大仓位进去」）
 #    实测过为什么不能做成 burst 扫描器：8/18 收盘时 COIN −2.87%/量比0.91×/收区间4%、
 #    PURR +0.70%/量比1.35×/收区间63% —— **T-1 的价格里没有任何爆发特征**，
 #    爆发发生在 8/19 当天。形态扫描只能第二天告诉你昨天涨了 ＝ 追高。
 #    **能提前抓到的是催化剂。**8/19 开盘前四条催化剂全都已存在。
 #    入选口径（四条，都是 T-1 就能知道的）：
 #      ① 今日 / 窗口内财报（earnings_calendar cache）
 #      ② 13F 新建仓或大幅加仓（scan_13f / X 转述）
 #      ③ **当日政策·监管日程**（白宫 / SEC / CFTC / 听证会 / FOMC）← 8/19 漏的就是这条
 #      ④ X 池点名 + 板块催化共振
 #    🔴 **2026-08-20 Vic：「EP 就不要管入场了，止损我盘中订，像日内一样入场，
 #       你提前发掘，我来 trade 先」** —— 所以这张表**不给入场位、不给止损、不给仓位**。
 #       它的职责收窄成一件事：**在开盘前把「今天该盯谁 ＋ 为什么」摆出来。**
 #       给入场位反而有害：EP 的入场是盘中第一根放量动量 bar，事前算的价位到点就是错的。
 #    列：TICKER / 催化剂 / 时间(ET·SGT，用 H.et_sgt) / 来源 / 为什么重要 / 盯什么
 #    🔴 **四条都空才允许 rows 为空**，且必须在 catalyst_watch_note 里写明逐条查过——
 #       空表和没查在页面上长得一样（QA 会拦）。
 "catalyst_watch": {"headers": ["TICKER", "催化剂", "时间（ET · SGT）", "来源",
                                 "为什么重要", "盯什么"],
                     "rows": [], "num_cols": [],
                     "table_class": "fixed-cols",
                     "col_widths": ["8%", "26%", "14%", "10%", "24%", "18%"]},
 "catalyst_watch_note": "",  ### 手写：没有候选时必须写「四条口径逐条查过」 ###
  "watchlist_abc": [],
 "setup_conclusion": "",
 "playbook_scenarios": [
   # 各情景带prob（合计必须=100，QA第7条会查）：
   #   {"title":"", "trigger":"", "action":"", "target":"", "prob":0}
   # 🔴键名就是 title/trigger/action/target——**写成 scenario/detail 会被字段名校验直接拦下**
   #   （2026-07-28修复：历史报告里情景标题和触发条件一直是空白的，就是键名写错且静默丢失）
 ],
 # 核心结论：每条写成 "**粗体标题句**|支撑句"（竖线分隔），渲染成黄色action-directive编号列表。
 # 英文小标题"KEY TAKEAWAYS"已删，不要再写。
 "key_takeaways": [],  ### 3-7条 ###
 "today_position": {"primary": [], "watch": [], "avoid": [], "invalidate": ""},
 # 🔴 2026-08-20 Vic：「纪律：今日不做 A 级以外的标的…这条太没用了！！！删除」——
 #    **自控/纪律条目不进这里**。它不是预测，盘后判 hit/miss 没有信息量，
 #    还占掉 5 条上限里的一格。纪律要写就写进 signal_light.discipline（黄色核心纪律卡）。
 #    validate_recon_ledger 现在会直接报错，写了过不了。
 "recon_ledger": [
   # 最多 5 条可证伪：{"claim":"", "prob":0.55}——只对大盘/板块/宏观打分，个股setup触发不预判
   # 🔴 **必须有一条加密**（2026-08-20 Vic），代理 IBIT / ETHB，例：
   #    {"claim": "**IBIT 今日收盘仍在 20MA 上方**（BTC 是否守住）", "prob": 0.55}
   #    H.validate_recon_ledger 会拦没有加密条目的台账。
   # 🔴 **纪律/自控不进这里**，写 signal_light.discipline。
 ],
 "x_watch_table": {"headers": ["提及日", "账号", "TICKER", "提及时价", "最新收盘", "自提及%", "备注"],
                    "rows": H.x_watch_rows(cache, pm), "num_cols": [3, 4, 5]},
 "x_watch_note": "",
 # ── 2026-08-10 回填：7/31 之后陆续加的字段，此前一直没回写进模板，
 #    导致模板残缺 →「用它反而丢字段」→ 更不用 → 更过期。
 #    这个循环是 8/10 格式大面积漂移的根因之一。
 #    🔴**以后每加一个字段，必须在同一次改动里回填这里。**
 "atr_extension_table": [],          ### H.atr_extension_rows(cache, H.INDEX_ORDER)
 "atr_extension_note": "",
 "dispersion": {},                   ### H.dispersion_reading(cache=cache, asof=...)
 "dispersion_note": "",
 "ftd": {},                          ### H.ftd_status()（已 parked，仍要出三态标记）
 "ftd_table": {},                    ### H.ftd_table(...)
 "ftd_note": "",                     ### 2026-08-11 补：一直在 PHASE1_FIELDS 里，却从没写进模板
 "bounce_table": {},                 ### 2026-08-06 起 parked（依赖 FTD），仍要出三态标记
 "bounce_note": "",                  ### 同上，2026-08-11 补进模板
 "position_governance_table": {},    ### H.position_governance_table(H.position_governance(pos))
 "position_governance_note": "",
 "stop_proximity_table": {},         ### H.stop_proximity_table(H.stop_proximity_rows(...))
 "stop_proximity_note": "",
 # 2026-08-11 Vic 点名要出 GLW/MRVL/SOXX/AAOI →「单独拉一张」。
 # EXIT_TICKERS 为空时整节不渲染（没人点名就没有这张表，不是漏了）。
 # 同一只票两个账户各有一笔时用 ("MRVL","longbridge") 精确指定，否则两笔都进表。
 "exit_plan_table": {},              ### H.exit_plan_table(H.exit_plan_rows(cache, EXIT_TICKERS, positions, pm))
 "exit_plan_note": "",               ### 手写：退出理由 + warnings 念给 Vic
 "week_calendar": {},                ### 六列日历：周一~周五 + 周末
 "x_sentiment_macro_summary": "",
 "breadth_table_note": "",
 "recon_prob_note": "",              ### 2026-08-08 对账事前概率的口径说明
 # 🔴 元素必须是 dict（ticker / catalyst / narrative / gap_pct / extreme / size / stop）。
 #    「今天没有」= **保持空 list**，build_event_gap_table 自带 placeholder 文案，
 #    空节照样看得见。**往里塞字符串 "无" 会让渲染器 AttributeError**
 #    （2026-08-14 踩到——原注释写的是「没有就写"无"」，把人误导了一次）。
 "event_gap_candidates": [],         ### 2026-08-09 事件缺口延续（空 list = 今日无候选）
 "event_gap_note": "",
 "bam": {},                          ### 2026-08-10 Deemer Breakaway Momentum
 "bam_table": {},
 "bam_note": "",
 "special_readthrough_table": {},    ### 2026-08-10 专题报告 read-through
 "special_readthrough_note": "",
 # 🔴 gate_scoreboard_rows / breadth_score_rows / cross_check 是 7/27 那次漂移的产物，
 #    **不是框架的一部分**。攻守记分板只有 scoreboard_rows 一张（四桶：
 #    upgrade / downgrade / duration / techparity）。它们目前仍留在数据里供
 #    cross_check_alignment 使用，但不算必备字段，也不要再往里搬条件。
 # 🔴 2026-08-17 起这是**唯一**的闸门表（etf_table 已退役）：VOO/QQQ/IWM 闸门行 +
 #    DIA/SMH/RSP/QQQE 参考行。GATE_NOTES 当天手写逐只判断。
# 🔴 2026-08-19 Vic：「voo qqq dia iwm smh rsp qqqe 表格里面好几张，你先都集中到一个地方」
 #    + 「指数闸门能用图示吗？一根横轴看位置」
 #    七只指数**只在这一个字段**：03 指数闸门渲染成「ATR 横轴图 + 一张全字段表」。
 #    随之在盘前停渲的两处（字段保留、只是不再画第二遍）：
 #      · sector_rs_tables 的「指数基准」组
 #      · atr_extension_table（原 01-C · 指数）——盘后/周报仍在用，不动
 "index_table": H.index_panel_rows(cache, GATE_NOTES),
 # 🔴 2026-08-20 起走 H.gate_rows：它只吐 GATE_TICKERS（VOO/QQQ/IWM/SMH）四只、
 #    且给 SMH 现算闸门线。index_panel_to_gate_rows 那条路会带回 DIA/RSP/QQQE 的参考行。
 "gate_scoreboard_rows": H.gate_rows(cache, GATE_NOTES),
 "breadth_score_rows": breadth9_rows(),
 "breadth_score_note": "",
 "cross_check": {},
 "footer_sources": "",
}

# ==========================================================================
# 开工自检（2026-08-12：两段式已取消，只剩一个桶）
# ==========================================================================
# 🔴 2026-08-11：开工自检——三个 phase 桶必须**恰好**覆盖本文件的字段集。
#    少了 → 落盘时被 keep 过滤掉 → **字段永久消失，而报告照样渲染**（已发生三次：
#    8/3 ftd/仓位治理、8/7 事件缺口、8/11 发现 bam/dispersion/stop_proximity 等 11 个）。
#    多了 → QA 会报「自造字段」。在这里先拦一道，不用等到渲染。
_RETIRED = {"futures_table", "futures_note",          # 2026-07-11 主动退役
            "premarket_movers", "premarket_movers_note",  # 2026-08-12 主动退役（盘前模块下线）
            "other_assets_table",                     # 2026-08-14 主动退役（改成 other_assets_note）
            "scoreboard_rows", "scoreboard_note",      # 2026-08-17 攻守记分板整块退役
            "breadth_table"}                           # 2026-08-17 并进 breadth_score_rows
_buckets = set(H.PHASE1_FIELDS)   # 2026-08-12 起只有这一个桶
# 下划线开头的是内部键（跟 QA 的 `not k.startswith("_")` 过滤一致），落盘时会被 keep 剔掉
_orphan = sorted(k for k in out
                 if not k.startswith("_") and k not in _buckets and k not in _RETIRED)
if _orphan:
    sys.exit("🔴 这些字段不在任何 phase 桶里，两段式跑法下会永久丢失：%s\n"
             "   去 scripts/report_helpers.py 把它们加进 PHASE1_FIELDS / "
             "PHASE2_PATCH_FIELDS / PHASE2_FIELDS 之一。" % _orphan)

# ==========================================================================
# 落盘（2026-08-12 起一次跑完；两段式已随盘前数据模块一起退役）
# ==========================================================================
keep = set(H.PHASE1_FIELDS)
draft = {k: v for k, v in out.items() if k in keep}

# 🔴 builder 戳（2026-08-11 Vic：「你今天的 pre market 是用了 builder 对吗」）——
#    字段名检查骗得过（手写把键抄齐就行），戳骗不过。QA 抬头每次都会念出来。
draft["_builder"] = "assemble_template.py"
draft["_builder_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")

# 当天全部 A 级候选写进 data/setup_track.json 台账（去重，见 CONTEXT「Setup A 专项对账」）。
# 必须在 watchlist_abc 手写填完之后、定稿之前调用。
n_new = H.sync_candidate_track(DAY, draft.get("watchlist_abc"))
if n_new:
    print(f"setup_track.json 新增 {n_new} 条候选跟踪")

p = H.save_premarket_draft(DAY, draft, phase=2, note="")
_filled = len([k for k in H.PHASE1_FIELDS if draft.get(k) not in (None, "", [], {})])
print(f"wrote {p}")
print(f"  字段 {_filled}/{len(H.PHASE1_FIELDS)} 有内容")
_empty = [k for k in H.PHASE1_FIELDS if draft.get(k) in (None, "", [], {})]
if _empty:
    print(f"  ⚠️ 还空着 {len(_empty)} 个（手写区没填完）：{_empty}")
print("  接着跑: python scripts/render_report.py", p)
