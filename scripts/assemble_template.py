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
RS_HEADERS = ["TICKER", "T-1%", "5日%", "1月%", "驱动/原因", "RS(1周)"]
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
    tickers = [r[0] for r in grp["rows"]]
    rows = H.sector_rs_rows(cache, tickers)
    hl = []
    for r in rows:
        r[4] = ""  ### 手写：驱动/原因列（只给有信息量的行写） ###
        hl.append("")
    rs_tables.append({"title": grp["title"], "headers": RS_HEADERS, "rows": rows,
                      "num_cols": [1, 2, 3, 5], "row_highlights": hl})

uni_rows, uni_hl = H.unilateral_rows(cache)      # hl: 距50MA≥5×ATR的行自动红底
# 2026-07-15 Vic："反弹观察区删除吧，没用"——F节已退役，不再调用H.oversold_rows()

# ---------- ETF技术总表 ----------
# 🔴顺序和成员由唯一常量 H.INDEX_ORDER 决定（2026-07-28 Vic定）：
#   VOO / QQQ / DIA / IWM / SMH / RSP / QQQE —— **全报告用VOO不用SPY，不要两个都写**。
#   盘前·指数、盘前·指数基准、盘后01收盘总结三处必须一致，QA第9条会逐表比对。
#   不要在这里手写ticker列表，改顺序去改 report_helpers.INDEX_ORDER。
etf_rows = H.gate_etf_rows(cache, H.INDEX_ORDER)
# ⚠️坑：sector_rs_rows() 内部按RS降序排，会把 INDEX_ORDER 打乱（2026-07-31 QA第9条抓到）。
#    建「指数基准」组之后必须再过一次 H.order_index_rows(rows) 重排回来。
etf_judge = {}  ### 手写：{"VOO": "判断", ...}；VOO/QQQ/IWM盘前%在snap里可能缺，用MCP值补 ###
pm_override = {}  # 退役 2026-08-12（原用于补 snap 缺失的盘前%），留空壳
for r in etf_rows:
    r[8] = etf_judge.get(r[0], "")   # 2026-08-12：不再往 T-1% 里塞「（盘前x%）」后缀

# ---------- 持仓表 ----------
mm_rows = H.positions_rows([p for p in positions if p["account"] == "moomoo"], cache)
lb_rows = H.positions_rows([p for p in positions if p["account"] == "longbridge"], cache)
mm_judge = {}  ### 手写：论点检查/今日行动 ###
lb_judge = {}  ### 手写 ###
# 🔴 2026-08-12：持仓表不再有「盘前」列（整个盘前数据模块退役）。表头 7 列、行 7 格，
# 不再需要段2 的 patcher 去插列 —— 那个「表头 8 列 / 行 7 格 → patcher 每天静默跳过」
# 的坑（8/10–8/11）也随之消失。
for rows, judge in ((mm_rows, mm_judge), (lb_rows, lb_judge)):
    for r in rows:
        r[6] = judge.get(r[0], "")
# 行高亮：盘前警报退役后暂时全空；要恢复就改成按「距止损 <0.7ATR」置 warn
mm_hl = ["" for _ in mm_rows]
lb_hl = ["" for _ in lb_rows]

# ---------- 防御篮子（2026-07-17起：ML Leader停用，Vic重新找leader中，见CONTEXT.md
# 「ML Market Leader名单」节——不再生成ml_rows，out字典也不再填ml_leaders/ml_leaders_note/
# leader_vs_defensive_note，render_report.py已改为这些字段缺失/空时不渲染方法1的Leader部分，
# 只留防御篮子表。Vic给新名单后，把ml_list换成新名单、照旧法生成ml_rows即可复原） ----------
def_rows = [{"ticker": r["ticker"], "price": str((M.get(r["ticker"]) or {}).get("close", "-")),
             "pct": "-", "role": "防御篮子"} for r in prev_json["defensive_basket"]]   # 2026-08-12：盘前列退役

# ---------- 方法2 setup扫描表（机器初筛→人眼过滤后展示） ----------
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
    if rs_of(r) > 0 or r[2].count("+") >= 1:
        focus.append(r)
strong_scores = {}  ### 手写：{"TICKER": "4", ...} 每行1-5打分（结构质量+板块方向+延伸度+催化共振） ###
strong_rows = [[r[0], r[1] if r[1] != "-" else "watchlist", r[2],
                r[3] + " / 9EMA" + r[4] + " / 量" + r[6], r[7][:60],
                strong_scores.get(r[0], "")] for r in focus[:18]]

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
 "scoreboard_rows": [
   # {"condition":"", "type":"upgrade|downgrade|duration|techparity", "threshold":"", "current":"", "distance_pct":"", "status":"met|unmet|triggered|safe"},
   # 升级用met(绿)/unmet(灰)；降级/防线用triggered(红)/safe(绿)；QQQ和VOO永远分行
 ],
 "scoreboard_note": "",  ### 周一：闸门线按cache['gate_reference']重算并请Vic确认 ###
 "risk_checklist": [
   # 9项固定：S&P 500 overextension / Increasing downward momentum / Top range breakdown /
   # Technical deterioration / Market breadth worsening / VIX >20 spike / 利率外生冲击 / 地缘外生冲击 / Theme momentum weakening
   # {"label":"", "level":"low|mid|high", "detail":""}
 ],
 "risk_checklist_note": "",
 "regime_triggers": {"upgrade": {"rule": "", "items": []}, "downgrade": {"rule": "", "items": []}},
 "breadth_table": {"headers": ["指标", "当前值", "前值", "判断"], "rows": [
   # 15项硬性checklist：①-⑥来自Vic Sheet「Maket breath」，⑦-⑮来自Stockbee表
 ], "num_cols": []},
 "other_assets_table": {"headers": ["资产", "现值", "日变动", "信号"], "rows": [
   # 顺序：10Y / VIX / DXY / 黄金 / 白银 / WTI / BTC
   # 🔴 **VIX1D 不单列一行**（Vic 2026-08-10 再次确认「vix1d说过去掉了」）——
   #    折进 VIX 那一行的「信号」列判断 Contango：VIX1D < VIX = 短端不紧张。
   # 🔴 MOVE 2026-07-21 起整行删除。
 ], "num_cols": [2]},
 "joint_signal_lines": [],  ### 手写：联合信号+覆盖指令检查 ###
 "macro_radar_table": {"headers": ["事件", "日期(ET)", "预期/前值", "结果/现状", "市场解读"], "rows": []},
 "macro_radar_detail": "",  ### 外部校对只认AP/IBD/MarketWatch+X池白名单 ###
 "sector_rs_tables": rs_tables,
 "sector_rs_note": "",
 # 🔴 2026-08-11 修：H.unilateral_rows() 产出 **10 格**（排名 / TICKER / 得分 / **阶段** /
 #    通过项 / 5日% / 1月% / RS / 距50MA / 延伸档位），而模板表头此前只写了 9 列——
 #    **「阶段」那一列被静默丢掉**。它不是 Vic 8/10 删掉的那个 Weinstein 独立小节，
 #    而是单边榜的 stage 过滤依据：8/11 那天 XSW / KWEB 原始得分 4/4 全场最高却落榜，
 #    正是因为 stage 3/4，不显示这一列根本看不出来为什么。
 "unilateral_scan_table": {"headers": ["排名", "TICKER", "得分", "阶段", "通过项", "5日%", "1月%", "RS(1周)", "距50MA", "延伸档位"],
                            "rows": uni_rows, "num_cols": [5, 6, 7], "row_highlights": uni_hl},
 "unilateral_scan_note": "",  ### 四件套：强势/可持有·修复/需确认·弱势/暂避·小结 ###
 "futures_table": {"headers": [], "rows": [], "num_cols": []},   # 2026-07-11已删除，留空壳
 "futures_note": "",
 "etf_table": {"headers": ["ETF", "收盘价", "T-1%（盘前%）", "进攻线(+1ATR)", "谨慎线(20MA)", "降级线(-1ATR)", "50MA", "距50MA", "判断"],
                "rows": etf_rows, "num_cols": [1, 2]},
 "etf_table_note": "",  ### 四件套 ###
 # 🔴 7 列。「盘前」列 2026-08-12 随盘前数据模块一起退役，不再由 patcher 插列
 "positions_moomoo_table": {"headers": ["TICKER", "现价", "成本", "距止损", "持有理由", "失效条件", "论点检查/今日行动"],
                             "rows": mm_rows, "num_cols": [], "row_highlights": mm_hl},
 "positions_moomoo_note": "",
 "positions_longbridge_table": {"headers": ["TICKER", "现价", "成本", "距止损", "持有理由", "失效条件", "论点检查/今日行动"],
                                  "rows": lb_rows, "num_cols": [], "row_highlights": lb_hl},
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
 "ml_leaders": [],  # 2026-07-17起停用，留空list（渲染层遇空自动跳过Leader部分），见上方防御篮子注释
 "ml_leaders_note": "",
 "defensive_basket": def_rows,
 "leader_vs_defensive_note": "",  # 同上，Leader停用期间不产出risk-on/risk-off联合信号
 "adanos_scan_table": {"headers": ["TICKER", "buzz", "热度变化", "趋势", "看多%", "盘前", "核实结论"],
   "rows": [], "num_cols": [1]},   # cache['adanos_movers']的surges+页面版Top10；cashtag污染必查
 "x_sentiment_macro": [
   # {"handle":"@x", "time":"", "summary":""}   ← dict格式，字符串会报错
 ],
 "x_sentiment_stocks": [
   # {"handle":"@x", "time":"", "ticker":"", "note":"", "aligned":""}
 ],
 "x_sentiment_note": "",  ### 新点名的票记得同步进 data/x_watch.json ###
 "thirteen_dg_rows": [],
 "thirteen_dg_note": "",
 "squeeze_candidates": [],
 "squeeze_note": "",
 "strong_sector_setups_table": {"headers": ["TICKER", "板块", "Setup标签", "RS(1周)/9EMA/量比", "机器说明", "评分(1-5)"],
                                  "rows": strong_rows, "num_cols": []},
 "strong_sector_setups_permission": "",  ### 手写：当日统一仓位/许可提醒（档位/事件纪律，全表适用，一句话） ###
 # 🔴A/B/C三级写同一个字段、同一组列（2026-07-28 Vic第三次要求统一后，
 #   watchlist_a / watchlist_b_table / watchlist_c 三个旧字段已在渲染器里**直接抛异常**）。
 #   每条：{"grade":"A|B|C", "ticker":"", "sector":"", "source":"", "setup":"",
 #          "entry":"", "invalid":"", "target":"", "note":""}
 #   A级最多5只、B级最多5只；source=CONTEXT.md「机会扫描」的方法号（"方法2"/"方法6·Vic肉眼"/"X trader"…），
 #   喂进 setup_track.json 台账（Setup A专项对账用）。
 #   要被识别成Setup A，setup字段必须显式含"Setup A"或"缩量回踩9EMA"字样。
 #   扫描永不冻结：档位只写进 permission 的许可标注，不允许空表。
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
 "recon_ledger": [
   # 5-8条可证伪：{"claim":"", "trigger":""}——只对大盘/板块/宏观打分，个股setup触发不预判
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
 "adanos_scan_note": "",
 "breadth_table_note": "",
 "recon_prob_note": "",              ### 2026-08-08 对账事前概率的口径说明
 "event_gap_candidates": [],         ### 2026-08-09 事件缺口延续（无条件生成，没有就写"无"）
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
 "gate_scoreboard_rows": [],
 "breadth_score_rows": [],
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
            "premarket_movers", "premarket_movers_note"}  # 2026-08-12 主动退役（盘前模块下线）
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
