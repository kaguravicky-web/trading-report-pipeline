#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前JSON组装模板（2026-07-13沉淀，源自Vic"沉淀吧"；2026-07-22改造成两段式）。

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

🔴**两段式（2026-07-22 Vic："盘前报告我想每次分两段跑，白天跑隔夜收盘和x账号，4点后跑盘前数据"）**
    python assemble_YYYYMMDD.py 1     # 段1·白天：隔夜收盘+X扫描 → 草稿_phase=1，不渲染
    python assemble_YYYYMMDD.py 2     # 段2·SGT16:00后：盘前报价 → 定稿_phase=2 → 再render

  段2**不会**重建段1那几张表（sector_rs/etf/持仓/防御篮子/setup扫描），只用
  `H.patch_premarket_columns()` 机械补一个盘前列，段1写的「驱动/原因」「判断」「论点检查」
  这些判断列原样保留。**如果盘前数据真的推翻了段1某一行的判断，手动改那一行，
  并在报告正文里写明"段1判X→段2见Y→改为Z"**，不要静默覆盖（判断的时间戳要可追溯）。

  每段开工先跑： python scripts/premarket_status.py

前置（段1必须先跑完）：
  python scripts/fetch_market_data.py      # cache/market_YYYYMMDD.json（校验data_date=上一交易日）
  python scripts/fetch_earnings_calendar.py
  python scripts/scan_semis_rsi.py
  python scripts/scan_setups.py [--sectors XL?,XL?]   # cache/setups_YYYYMMDD.json
前置（段2）：
  python scripts/snap_premarket.py         # cache/premarket_YYYYMMDD.json（先看pm_stale比例！）

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
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import report_helpers as H

PHASE = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] in ("1", "2") else 1
DS = date.today().strftime("%Y%m%d")          # 或手动指定 "20260713"
DAY = date.today().isoformat()

cache = H.load_cache(DS)
if cache.get("data_date") == DAY:
    sys.exit(f"🔴 cache的data_date={DAY}等于报告日本身——fetch跑在美股收盘前，拿到的不是完整"
             f"收盘数据。等美股收盘（SGT 04:00后）重跑 fetch_market_data.py")
pm = H.load_premarket_snap(DS) if PHASE == 2 else {}
if PHASE == 2:
    if not pm:
        sys.exit("🔴 段2需要盘前快照但 cache/premarket_%s.json 不存在——先跑 snap_premarket.py" % DS)
    _stale = [k for k, v in pm.items() if isinstance(v, dict) and v.get("pm_stale")]
    if len(_stale) > len(pm) * 0.5:
        sys.exit(f"🔴 {len(_stale)}/{len(pm)} 只标记pm_stale——盘前报价是上一时段残留，"
                 f"现在跑段2会把涨跌算反。确认已过SGT 16:00后重跑 snap_premarket.py")
setups = H.load_setups(DS)
# 2026-07-16 Vic："以后持仓，只扫描我的tradebook"——不再读data/positions.json/查LongBridge MCP
# /比对moomoo CSV，直接从Vic自己维护的data/tradebook.json派生当前持仓（见H.load_tradebook_positions
# 文档字符串）。已知代价：tradebook里没录的仓位不会出现，Vic要自己保证及时录入。
positions = H.load_tradebook_positions()
M = cache["metrics"]

def pmp(tk, default="无盘前quote"):
    v = (pm.get(tk) or {}).get("pm_pct")
    return ("%+.2f%%" % v) if v is not None else default

# ---------- RS三组（ticker列表沿用上一份报告，机械填充+判断列手写） ----------
# 2026-07-15 Vic改版列：T-1% / 5日% / 1月% / 盘前 / 驱动 / RS(1周)——表头固定在这里，不再继承旧报告
# （当天先试了RS(1日/5日)双值格式，Vic当天纠正"只看一周的，说过了"——全报告RS统一单值1周）
RS_HEADERS = ["TICKER", "T-1%", "5日%", "1月%", "盘前", "驱动/原因", "RS(1周)"]
prev = sorted((ROOT / "data/daily").glob("*-premarket.json"))[-1]
prev_json = json.load(open(prev, encoding="utf-8"))
rs_tables = []
for grp in prev_json["sector_rs_tables"]:
    tickers = [r[0] for r in grp["rows"]]
    rows = H.sector_rs_rows(cache, tickers, pm)
    hl = []
    for r in rows:
        pmv = (pm.get(r[0]) or {}).get("pm_pct")
        r[5] = ""  ### 手写：驱动/原因列（只给有信息量的行写） ###
        hl.append("warn" if (pmv is not None and pmv <= -4) else ("bull" if (pmv is not None and pmv >= 4) else ""))
    rs_tables.append({"title": grp["title"], "headers": RS_HEADERS, "rows": rows,
                      "num_cols": [1, 2, 3, 4, 6], "row_highlights": hl})

uni_rows, uni_hl = H.unilateral_rows(cache)      # hl: 距50MA≥5×ATR的行自动红底
# 2026-07-15 Vic："反弹观察区删除吧，没用"——F节已退役，不再调用H.oversold_rows()

# ---------- ETF技术总表 ----------
# 🔴顺序和成员由唯一常量 H.INDEX_ORDER 决定（2026-07-28 Vic定）：
#   VOO / QQQ / DIA / IWM / SMH / RSP / QQQE —— **全报告用VOO不用SPY，不要两个都写**。
#   盘前B·指数、盘前E·指数基准、盘后01收盘总结三处必须一致，QA第9条会逐表比对。
#   不要在这里手写ticker列表，改顺序去改 report_helpers.INDEX_ORDER。
etf_rows = H.gate_etf_rows(cache, H.INDEX_ORDER)
# ⚠️坑：sector_rs_rows() 内部按RS降序排，会把 INDEX_ORDER 打乱（2026-07-31 QA第9条抓到）。
#    建「指数基准」组之后必须再过一次 H.order_index_rows(rows) 重排回来。
etf_judge = {}  ### 手写：{"VOO": "判断", ...}；VOO/QQQ/IWM盘前%在snap里可能缺，用MCP值补 ###
pm_override = {}  ### 手写：{"VOO": "-0.27%", ...} snap缺失时的盘前%覆盖 ###
for r in etf_rows:
    r[2] = r[2] + "（盘前" + (pm_override.get(r[0]) or pmp(r[0])) + "）"
    r[8] = etf_judge.get(r[0], "")

# ---------- 持仓表 ----------
mm_rows = H.positions_rows([p for p in positions if p["account"] == "moomoo"], cache)
lb_rows = H.positions_rows([p for p in positions if p["account"] == "longbridge"], cache)
mm_judge = {}  ### 手写：论点检查/今日行动 ###
lb_judge = {}  ### 手写 ###
for rows, judge in ((mm_rows, mm_judge), (lb_rows, lb_judge)):
    for r in rows:
        alert = H.position_pm_alert(pm, r[0])  # 2026-07-15 SYK教训：持仓盘前量/价异动必须跳出来
        r[1] = str(r[1]) + "（盘前" + pmp(r[0], "-") + "）" + ((" " + alert) if alert else "")
        r[6] = judge.get(r[0], "")
mm_hl = ["warn" if H.position_pm_alert(pm, r[0]) else "" for r in mm_rows]
lb_hl = ["warn" if H.position_pm_alert(pm, r[0]) else "" for r in lb_rows]

# ---------- 防御篮子（2026-07-17起：ML Leader停用，Vic重新找leader中，见CONTEXT.md
# 「ML Market Leader名单」节——不再生成ml_rows，out字典也不再填ml_leaders/ml_leaders_note/
# leader_vs_defensive_note，render_report.py已改为这些字段缺失/空时不渲染方法1的Leader部分，
# 只留防御篮子表。Vic给新名单后，把ml_list换成新名单、照旧法生成ml_rows即可复原） ----------
def_rows = [{"ticker": r["ticker"], "price": str((M.get(r["ticker"]) or {}).get("close", "-")),
             "pct": "盘前" + pmp(r["ticker"]), "role": "防御篮子"} for r in prev_json["defensive_basket"]]

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
   # 顺序：10Y / MOVE / VIX(信号列折VIX1D Contango判断) / DXY / F&G / 黄金 / 铜 / WTI / BTC / KOSPI / 日经 / 恒指 / 上证
 ], "num_cols": [2]},
 "joint_signal_lines": [],  ### 手写：联合信号+覆盖指令检查 ###
 "macro_radar_table": {"headers": ["事件", "日期(ET)", "预期/前值", "结果/现状", "市场解读"], "rows": []},
 "macro_radar_detail": "",  ### 外部校对只认AP/IBD/MarketWatch+X池白名单 ###
 "sector_rs_tables": rs_tables,
 "sector_rs_note": "",
 "unilateral_scan_table": {"headers": ["排名", "TICKER", "得分", "通过项", "5日%", "1月%", "RS(1周)", "距50MA", "延伸档位"],
                            "rows": uni_rows, "num_cols": [4, 5, 6], "row_highlights": uni_hl},
 "unilateral_scan_note": "",  ### 四件套：强势/可持有·修复/需确认·弱势/暂避·小结 ###
 "futures_table": {"headers": [], "rows": [], "num_cols": []},   # 2026-07-11已删除，留空壳
 "futures_note": "",
 "etf_table": {"headers": ["ETF", "收盘价", "T-1%（盘前%）", "进攻线(+1ATR)", "谨慎线(20MA)", "降级线(-1ATR)", "50MA", "距50MA", "判断"],
                "rows": etf_rows, "num_cols": [1, 2]},
 "etf_table_note": "",  ### 四件套 ###
 "positions_moomoo_table": {"headers": ["TICKER", "现价", "成本", "距止损", "持有理由", "失效条件", "论点检查/今日行动"],
                             "rows": mm_rows, "num_cols": [], "row_highlights": mm_hl},
 "positions_moomoo_note": "",
 "positions_longbridge_table": {"headers": ["TICKER", "现价", "成本", "距止损", "持有理由", "失效条件", "论点检查/今日行动"],
                                  "rows": lb_rows, "num_cols": [], "row_highlights": lb_hl},
 "news_today": [],   ### Trump/战争第一优先级；重大消息必须WebSearch交叉核实 ###
 "news_week": [],
 "industry_radar_table": {"headers": ["主题", "信号", "解读"], "rows": [], "num_cols": []},
 "premarket_movers": [
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
 "position_governance_table": {},    ### H.position_governance_table(H.position_governance(pos))
 "position_governance_note": "",
 "stop_proximity_table": {},         ### H.stop_proximity_table(H.stop_proximity_rows(...))
 "stop_proximity_note": "",
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
# 落盘：两段式分支（2026-07-22）
# ==========================================================================
if PHASE == 1:
    # 段1只保留自己该定稿的字段 + 待段2补盘前列的骨架表，其余键剔掉，
    # 免得段2看到一堆空壳误以为"段1填过了"
    keep = set(H.PHASE1_FIELDS) | set(H.PHASE2_PATCH_FIELDS)
    draft = {k: v for k, v in out.items() if k in keep}
    ### 手写：给Vic的隔夜结论摘要（3-5句，白天就能读；这也是段1唯一的交付物） ###
    phase1_note = ""
    p = H.save_premarket_draft(DAY, draft, phase=1, note=phase1_note)
    print(f"段1草稿 → {p}（_phase=1，**不渲染**）")
    print(f"  已定稿字段 {len([k for k in H.PHASE1_FIELDS if k in draft])}/{len(H.PHASE1_FIELDS)}")
    print("  下一步：SGT 16:00后跑 snap_premarket.py，再跑本脚本 phase=2")
    print("  现在在对话里给Vic讲隔夜结论，不要贴整份报告")
else:
    # 段2：读段1草稿 → 机械补盘前列 → 覆盖/新增段2字段 → 定稿
    draft, warns = H.load_premarket_draft(DAY)
    if draft is None:
        sys.exit("\n".join(warns))
    for w in warns:
        print(w)                      # ← 这些要念给Vic听，不要静默吞掉
    for c in H.patch_premarket_columns(draft, pm):
        print("  patch:", c)
    # 段2独有字段 + 段2重建的表，覆盖进草稿；段1的判断列不动
    for k in H.PHASE2_FIELDS:
        if k in out:
            draft[k] = out[k]
    ### 手写：若盘前数据推翻了段1某行判断，在这里手动改那一行，并把"段1判X→段2见Y→改为Z"
    ### 写进 key_takeaways 或对应表的note——不要静默覆盖 ###

    # 2026-07-15：当天全部A级候选（不限setup类型）写入 data/setup_track.json 台账（去重，
    # 见CONTEXT.md「Setup A专项对账」）。必须在watchlist_a手写填完之后、定稿之前调用。
    n_new = H.sync_candidate_track(DAY, draft.get("watchlist_abc"))
    if n_new:
        print(f"setup_track.json 新增 {n_new} 条候选跟踪")
    p = H.save_premarket_draft(DAY, draft, phase=2)
    print("wrote", p, "→ 接着跑: python scripts/render_report.py", p)
