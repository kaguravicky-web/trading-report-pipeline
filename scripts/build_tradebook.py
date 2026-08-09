#!/usr/bin/env python3
"""本地TradeBook v2（2026-07-08，Vic要求可自助维护——编辑/删除按钮齐全，省token也保留"亲手记录亏损"的复盘价值）。

职责划分：
  - Vic：在 output/tradebook.html 页面上直接增删改（交易/legs/止损历史/复盘评分/他自己的每日总结），
    点「保存」写回 data/tradebook.json（Chrome的File System Access API，首次选一次文件，之后记住）
  - Claude：每日盘后跑本脚本一次——自动把 data/daily/*-postmarket.json 的 tradebook_block 导入
    daily_summaries[].summary（Claude的总结），并重建HTML。Vic的所有字段原样保留。

字段（v2新增）：setup_type（Momentum Burst/Episodic Pivot/Base Breakout/Pullback/Other）·
planned（Planned/Unplanned）· stop_history[]（移动止损全历史）· target（算R:R）·
legs[].decision_score（每次操作1-5决策评分）· review{}（卖后追踪：卖飞/shakeout-liquidity grab/追入/突破向下卖出）·
day_trade（日内勾选）· 持仓天数自动算 · entry_logic/exit_logic（买入/卖出逻辑）·
daily_summaries[].vic_summary（Vic自己写的总结，与Claude的分开）

v3新增（2026-07-16，Vic UI反馈11条）：搜索框（代码/逻辑关键词） · 持仓中/已平仓/每日总结三个标签页 ·
账户色标（moomoo橘黄/LongBridge蓝） · 跟老师的交易隐藏买卖逻辑与决策分 · 建仓日期=初始止损日期自动同步
（不再重复填） · 卖出逻辑允许留空+预设标签（板块转弱/fakeout/大市不好/减仓观望/setup failed） ·
日内交易不用选setup类型 · 卖出价=止损价时该笔笔记/决策分免填（视为止损单触发） · 已平仓标签页筛选器
（日内/跟老师的/盈利/亏损/卖飞/被shakeout/突破向下） · undercut字段改标签为「shakeout or liquidity grab」
（字段key不变，兼容旧数据）

v3.1（2026-07-23，Vic反馈）：止损轨迹每条记录自动算风险绝对值和%（相对均价，正=还有多少风险，
负=已保本+多少）· 删除"初始风险/股"统计（Vic觉得多余） · **撤销ATR建议止损功能**（Vic原话："我觉得
很复杂，用了每次只是扩大亏损而已，我每次止损都是股票单日动能下跌超过1ATR了"——他的止损纪律本来就是
按1ATR单日动能砍出，ATR建议止损反而会诱导他放宽止损、加大亏损，跟他的实际风控逻辑相反；ATR数值他
自己用TradingView看，不需要这里算），scripts/suggest_stops.py已删除，CONTEXT.md里对应的盘后步骤和
说明段落也已移除。

v3.2（2026-07-28，"改的又没了"第二轮事故修复）：loadFresh()读不到最新文件（File System Access权限
跨会话/隔天可能没保留，浏览器行为，本App管不了）时不再默默显示旧的嵌入快照，改成显眼黄色横幅+
「点击刷新最新数据」按钮（必须用户点击触发requestPermission，不能自动弹）；横幅存在时保存会先弹确认框，
防止拿旧快照当底稿覆盖掉没读到的修改。详见CONTEXT.md「TradeBook联动规则」2026-07-28条目。

v4（2026-08-07，Vic："输入太多，几个trade输入半天，有时候不知道输入什么就大概填一下，页面也不好看"）：
工作流已变成"CSV丢给Claude导客观数据→Vic只补主观判断"，表单按新工作流减负+页面美化：
①决策分从每leg一个改成每笔交易一个execution_score（legs[].decision_score历史保留但UI不再显示）
②买入逻辑加预设标签（突破buy point/tight盘整/shakeout+LG/板块强势/回踩支撑/巨量/财报事件/日内突破）
③空白标红改白名单制：只有ticker/股数/价格/初始止损标红，其他字段允许空着——不知道填什么就留空，
  空白本身就是复盘信息，硬填的假数据反而污染统计
④新增「待补齐」标签页：列出缺setup/买入逻辑/执行分/卖后结果的已平仓交易，行内下拉直接补，不用逐笔展开
⑤已平仓卡片默认折叠成一行摘要（ticker+日期+盈亏+R），点击展开
⑥KPI区下加月度盈亏柱状图+按setup类型的胜率分解表

v3.3（2026-07-30，卖后追踪改互斥单选）：Vic反馈"卖飞了吗/是shakeout or liquidity grab吗/是否卖在
突破向下"这几个问题不会同时发生，undercut后追入了吗是shakeout的二阶追问，之前4个都平级摆成独立
是/否/未评，容易填出自相矛盾的组合（比如同一笔既标是shakeout又标卖在突破向下）。改成一个互斥单选
（未评/卖飞了/是shakeout-liquidity grab/卖在真突破向下/都不是），只有选中shakeout时才展开"追入了吗"
这个二阶问题。底层数据字段（review.sell_fly/undercut/chase_reentry/breakdown_sell）不变，只是现在选一个
选项会把其余互斥字段自动置为false，保证不会再出现矛盾组合；已平仓筛选器（卖飞的/被shakeout/突破向下）
逻辑不用改。同样加了applyReviewOutcome()给commitFormLight()捕获，避免选完outcome后点"加一笔"之类操作
把选择冲掉（跟ticker那个bug是同一类问题，见v3.1）。
"""
import json
import pathlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "templates" / "report.css"
TB_PATH = ROOT / "data" / "tradebook.json"
DAILY = ROOT / "data" / "daily"
OUT = ROOT / "output" / "tradebook.html"

SETUP_TYPES = ["Momentum Burst", "Episodic Pivot", "Base Breakout", "Pullback", "No Setup"]


def migrate(store):
    """老记录补齐v2字段，幂等。"""
    for t in store.get("trades", []):
        t.setdefault("setup_type", None)
        t.setdefault("planned", None)          # true/false/null(未标注)
        t.setdefault("day_trade", False)
        t.setdefault("mentor", False)          # 跟老师的交易标记（2026-07-09 Vic要求）
        t.setdefault("target", None)
        t.setdefault("entry_logic", t.get("thesis", ""))
        t.setdefault("exit_logic", "")
        if "stop_history" not in t:
            t["stop_history"] = ([{"date": t.get("entry_date"), "stop": t["stop_initial"], "note": "初始止损"}]
                                 if t.get("stop_initial") else [])
        t.setdefault("review", {"sell_fly": None, "undercut": None, "chase_reentry": None,
                                "breakdown_sell": None, "note": ""})
        t["review"].setdefault("window", None)   # 复盘周期 3d/1w/2w（2026-08-08 Vic）
        for l in t.get("legs", []):
            l.setdefault("decision_score", None)
        # v4（2026-08-07）：决策分从"每leg一个"改成"每笔交易一个"（Vic：一天4进4出要评8次受不了）。
        # legs[].decision_score历史数据保留不删，但UI不再显示；迁移时取已有leg分的均值四舍五入作初始值。
        if "execution_score" not in t:
            scores = [l["decision_score"] for l in t.get("legs", []) if l.get("decision_score")]
            t["execution_score"] = round(sum(scores) / len(scores)) if scores else None
        # v5（2026-08-07）：执行分1-5退化成了盈亏复读机（Vic："我都写了3…亏钱就是1赚钱就是5"），
        # 换成跟盈亏解耦的execution_quality(clean/flawed/chaotic)+execution_flags[]。
        # **不迁移旧的execution_score**——那批数据本身就是噪音，按它推导质量等于把噪音洗成"看起来有意义"。
        t.setdefault("execution_quality", None)
        t.setdefault("execution_flags", [])
        # v5.1（2026-08-09）：动作之外记"当时的状态"——Vic："wolf 我就是在没自信的状态下
        # 交易了拿不住"。execution_flags 记做错了什么动作，这两个字段记人当时是什么状态，
        # 同一个动作背后可能是没信心也可能是想扳回来，分开才知道该修哪一头。
        t.setdefault("execution_states", [])
        t.setdefault("execution_note", "")
        # 2026-08-08：Setup里的"Other"直接改叫"No Setup"，原来那个额外的no_setup勾选框取消
        # （Vic："直接把other改成无明确setup就好了"）。老数据统一迁过来，no_setup字段就此退役。
        if t.get("setup_type") == "Other":
            t["setup_type"] = "No Setup"
        if t.get("no_setup") and not t.get("setup_type"):
            t["setup_type"] = "No Setup"
        t.setdefault("no_setup", False)      # 已退役，保留字段只为兼容老数据不报错
        # catalyst字段2026-08-08废弃（Vic："催化剂我会在买入逻辑里面写"），
        # 不再有输入框；老数据里已有的值保留不删，卡片上还照常显示。
        t.setdefault("catalyst", "")
        # 日内/跟老师的没有planned一说，统一清成null
        if t.get("day_trade") or t.get("mentor"):
            t["planned"] = None
        # 2026-07-08：execution_notes与leg备注重复，Vic要求删除——内容并入最后一条leg的备注，不丢历史
        en = t.pop("execution_notes", None)
        if en and t.get("legs"):
            last = t["legs"][-1]
            existing = last.get("note") or ""
            if en not in existing:
                last["note"] = (existing + "；" if existing else "") + en
        # 2026-07-08：平仓状态自动判定——没有剩余股数就是平仓，平仓日=最后一笔卖出日（Vic要求，不再手填）
        buys = sum(l["qty"] for l in t.get("legs", []) if l["action"] == "buy")
        sells = sum(l["qty"] for l in t.get("legs", []) if l["action"] == "sell")
        if t.get("legs") and buys - sells <= 0:
            t["status"] = "closed"
            sell_dates = [l["date"] for l in t["legs"] if l["action"] == "sell" and l.get("date")]
            if sell_dates:
                t["exit_date"] = max(sell_dates)
        elif t.get("legs"):
            t["status"] = "open"
            t["exit_date"] = None
    for s in store.get("daily_summaries", []):
        s.setdefault("vic_summary", None)
        s.setdefault("vic_grade", None)
        s.setdefault("vic_biggest_mistake", None)
        s.setdefault("vic_best_decision", None)
    return store


def import_summaries(store):
    """把Claude的**周报**总结自动灌进「每周复盘」页（2026-08-08 Vic：「你把你的周报总结自动放进去，
    我每天爱加就加一句」）。以前灌的是每日盘后总结全文，Vic说那页他不看，已经停掉。

    数据源：data/daily/YYYY-Www-weekly.json 的 title / subtitle / core_conclusions。
    按ISO周换算成那周的**周一日期**当key，跟页面上的周行对齐。
    只写Claude自己的`summary`字段，**绝不碰Vic写的`vic_summary`**。
    """
    from datetime import date as _date
    by_date = {s["date"]: s for s in store["daily_summaries"]}
    for f in sorted(DAILY.glob("*-weekly.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = re.match(r"(\d{4})-W(\d{1,2})", str(d.get("week") or f.name))
        if not m:
            continue
        try:
            monday = _date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1).isoformat()
        except ValueError:
            continue
        parts = []
        if d.get("title"):
            parts.append(str(d["title"]).strip())
        if d.get("subtitle"):
            parts.append(str(d["subtitle"]).strip())
        for c in (d.get("core_conclusions") or []):
            head, _, body = str(c).partition("|")
            parts.append("• " + head.strip() + (("\n" + body.strip()) if body.strip() else ""))
        block = "\n\n".join(p for p in parts if p)
        if not block:
            continue
        s = by_date.get(monday)
        if s is None:
            s = {"date": monday, "summary": None, "vic_summary": None, "vic_grade": None,
                 "vic_biggest_mistake": None, "vic_best_decision": None}
            store["daily_summaries"].append(s)
            by_date[monday] = s
        s["summary"] = block      # 周报重跑会覆盖自己写的这份，但vic_summary原样不动
        # 标记来源：老的每日盘后总结里也有summary字段，恰好落在周一的会被误当成周报显示出来。
        # 只有带这个标记的才在「每周复盘」页展示正文。
        s["summary_kind"] = "weekly"
    store["daily_summaries"].sort(key=lambda s: s["date"], reverse=True)


APP_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TradeBook · 本地交易日志</title>
<style>
__CSS__
body{font-size:16px}
.topbar{position:sticky;top:0;z-index:50;display:flex;gap:10px;align-items:center;background:rgba(255,255,255,.97);
  border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:14px;flex-wrap:wrap}
.btn{cursor:pointer;border:1px solid var(--line);background:#fff;border-radius:9px;padding:7px 14px;font-size:14.5px;font-weight:700}
.btn:hover{background:#f2f5f8}
.btn.primary{background:var(--blue);color:#fff;border-color:var(--blue)}
.btn.danger{color:var(--red);border-color:#e4c4bb}
.btn.small{padding:3px 9px;font-size:13px;border-radius:7px}
.dirty{color:var(--red);font-weight:800;font-size:14px}
.saved-ok{color:var(--green);font-weight:800;font-size:14px}
.trade{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0;box-shadow:0 8px 20px rgba(15,23,42,.04)}
.thead-line{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.tk{font-size:24px;font-weight:800}
.chip{font-size:12.5px;font-weight:700;border-radius:6px;padding:2px 9px;border:1px solid var(--line);color:var(--muted)}
.chip.setup{color:var(--blue);background:var(--blue-bg);border-color:#c3d6f5}
.chip.planned{color:var(--green);background:var(--green-bg);border-color:#bfe0cd}
.chip.unplanned{color:var(--red);background:var(--red-bg);border-color:#eccabf}
.chip.daytrade{color:#fff;background:var(--blue);border-color:var(--blue)}
.chip.open{color:var(--green);background:var(--green-bg)}
.chip.closed{color:var(--muted);background:#eef0f3}
.chip.hold-short{color:var(--amber);background:var(--amber-bg);border-color:#e8c3b8}
.chip.acct-mm{color:#fff;background:#e08a2c;border-color:#e08a2c}
.chip.acct-lb{color:#fff;background:var(--blue);border-color:var(--blue)}
.rowbtns{margin-left:auto;display:flex;gap:6px}
.searchbox{flex:1;min-width:180px;display:flex;align-items:center;gap:6px}
.searchbox input{width:100%;box-sizing:border-box;font-size:14.5px;padding:7px 10px;border:1px solid var(--line);border-radius:9px;font-family:inherit}
.tabs{display:flex;gap:2px;margin-bottom:14px;border-bottom:2px solid var(--line);flex-wrap:wrap}
.tabbtn{cursor:pointer;border:none;background:none;padding:9px 16px;font-size:14.5px;font-weight:700;color:var(--muted);
  border-bottom:3px solid transparent;margin-bottom:-2px}
.tabbtn:hover{color:var(--text)}
.tabbtn.active{color:var(--blue);border-bottom-color:var(--blue)}
.filterbar{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 14px}
.fchip{cursor:pointer;border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 12px;font-size:13.5px;font-weight:700;color:var(--muted)}
.fchip.active{background:var(--blue);color:#fff;border-color:var(--blue)}
.tagbtns{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 0}
.tagbtn{cursor:pointer;border:1px dashed var(--line);background:#fff;border-radius:7px;padding:3px 10px;font-size:12.5px;color:var(--muted)}
.tagbtn:hover{background:var(--blue-bg);border-color:#c3d6f5;color:var(--blue)}
.tagbtn.on{border-style:solid;background:var(--red-bg);border-color:#eccabf;color:var(--red);font-weight:700}
/* v5.1 表单控件统一：字段行 + 分段按钮，所有控件等高，不再混裸checkbox */
.frow{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:4px}
.fld{display:flex;flex-direction:column;min-width:0}
.fld.grow{flex:1 1 190px}
.fld label{display:block;font-size:12.5px;font-weight:700;color:var(--muted);margin-bottom:4px}
.fld input,.fld select{height:38px;box-sizing:border-box;font-size:15px;padding:0 9px;
  border:1px solid #cfd6de;border-radius:9px;background:#fff;font-family:inherit}
.seg{display:flex;height:38px;border:1px solid #cfd6de;border-radius:9px;overflow:hidden;background:#fff}
.segbtn{cursor:pointer;border:none;background:#fff;padding:0 14px;font-size:14px;font-weight:700;color:var(--muted);
  font-family:inherit;border-right:1px solid #e6e8ec;white-space:nowrap}
.seg .segbtn:last-child{border-right:none}
.segbtn:hover{background:#f2f5f8;color:var(--text)}
.segbtn.on{background:var(--blue);color:#fff}
.segbtn.tog.on{background:var(--text);color:#fff}
/* 执行质量三档：浅绿→浅红 */
.qchips{display:flex;gap:8px;flex-wrap:wrap}
.qchip{cursor:pointer;height:36px;padding:0 16px;border-radius:9px;font-size:14.5px;font-weight:700;font-family:inherit;
  border:1px solid var(--line);background:#fff;color:var(--muted)}
.qchip:hover{background:#f4f6f8}
.qchip.q-good.on{background:var(--green-bg);border-color:var(--soft-green);color:var(--green)}
.qchip.q-mid.on{background:#f1f3f5;border-color:#c4ccd4;color:#5b636c}
.qchip.q-bad.on{background:var(--red-bg);border-color:var(--soft-red);color:var(--red)}
.execblock{background:#fbfcfd;border:1px solid var(--line);border-radius:10px;padding:10px 13px;margin:6px 0}
.execblock select{font-size:14.5px;padding:6px 9px;border:1px solid #cfd6de;border-radius:8px;background:#fff;font-family:inherit;width:100%}
/* v4: 已平仓折叠行 */
.trow{display:flex;align-items:center;gap:10px;background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:9px 14px;margin:6px 0;cursor:pointer;flex-wrap:wrap}
.trow:hover{background:#f6f9fc;border-color:#c3d6f5}
.trow .tk2{font-size:16.5px;font-weight:800;min-width:64px}
.trow .dot{width:9px;height:9px;border-radius:50%;flex:none}
.trow .dot.mm{background:#e08a2c}.trow .dot.lb{background:var(--blue)}
.trow .dates{color:var(--muted);font-size:13px;min-width:106px}
.trow .pnl{font-variant-numeric:tabular-nums;font-weight:800;min-width:150px}
.trow .pnl.up{color:var(--green)}.trow .pnl.dn{color:var(--red)}
.trow .minichips{display:flex;gap:5px;flex-wrap:wrap;margin-left:auto}
.trow .chip{font-size:11.5px;padding:1px 7px}
/* v4: 待补齐表格 */
.todo-table{width:100%;border-collapse:collapse;font-size:14px}
.todo-table th{text-align:left;color:var(--muted);font-size:12.5px;padding:7px 9px;border-bottom:2px solid var(--line)}
.todo-table td{padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:middle}
.todo-table select,.todo-table input{font-size:13.5px;padding:4px 7px;border:1px solid #cfd6de;border-radius:7px;background:#fff;font-family:inherit;max-width:170px}
.todo-table .miss{color:#b95c38;font-weight:700}
.todo-done{color:var(--green);font-weight:700}
/* v4: 统计区 */
/* 每周复盘：Claude的周报总结（自动）+ Vic随手加的一句 */
.wkcard{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin:12px 0;
  box-shadow:0 8px 20px rgba(15,23,42,.04)}
.wkhead{font-size:13px;font-weight:800;color:var(--muted);letter-spacing:.05em;margin-bottom:8px;
  font-variant-numeric:tabular-nums}
.wk-title{font-size:16.5px;font-weight:800;line-height:1.5;margin-bottom:5px}
.wk-sub{font-size:13.5px;color:var(--muted);line-height:1.6;margin-bottom:10px}
.wk-pt{border-left:3px solid #cfd6de;background:#fbfcfd;border-radius:0 8px 8px 0;padding:8px 12px;margin:7px 0}
.wk-pth{font-size:14px;font-weight:700;line-height:1.6}
.wk-ptb{font-size:13.5px;color:#4b5563;line-height:1.65;margin-top:4px;white-space:pre-wrap}
.wk-body{margin-bottom:12px}
.wk-input{margin-top:2px}
.dl-input{width:100%;box-sizing:border-box;height:34px;font-size:14.5px;padding:0 10px;
  border:1px solid transparent;border-radius:8px;background:#fbfcfd;font-family:inherit}
.daily-table .dl-input:hover{border-color:#e0e3e8}
.daily-table .dl-input:focus{border-color:#c3d6f5;background:#fff;outline:none}
.statsblock{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin:12px 0}
.statsblock h3{margin:0 0 10px;font-size:15px;color:var(--muted);letter-spacing:.03em}
.mbars{display:flex;align-items:flex-end;gap:14px;height:120px;padding:0 4px}
.mbar{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;min-width:44px}
.mbar .bar{width:70%;border-radius:5px 5px 0 0;min-height:2px}
.mbar .bar.up{background:var(--green)}.mbar .bar.dn{background:var(--red);border-radius:0 0 5px 5px}
.mbar .mlabel{font-size:11.5px;color:var(--muted);margin-top:5px;white-space:nowrap}
.mbar .mval{font-size:12px;font-weight:800;font-variant-numeric:tabular-nums;white-space:nowrap}
.mbar .mval.up{color:var(--green)}.mbar .mval.dn{color:var(--red)}
/* v4.1: Setup A 命中率分析图表 */
.sa-kpis{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 14px}
.sa-kpi{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:11px;
  padding:9px 15px;min-width:104px;box-shadow:0 4px 12px rgba(15,23,42,.04)}
.sa-kpi span{display:block;font-size:12px;color:var(--muted);font-weight:700}
.sa-kpi strong{font-size:21px;font-variant-numeric:tabular-nums}
.sa-kpi.hit{border-left-color:var(--green)}.sa-kpi.miss{border-left-color:var(--red)}
/* 结果分布柱状图：四根独立柱子。配色沿用红绿二色系统——命中=浅绿、失误=浅红、
   部分/过期=两档浅灰（"部分"是中性结果，不占用第三种色相，2026-07-06定案） */
.rbars{display:flex;align-items:flex-end;gap:22px;padding:4px 6px 0;flex-wrap:wrap}
.rbar{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:74px}
.rb-val{font-size:15px;font-weight:800;font-variant-numeric:tabular-nums;margin-bottom:4px}
.rb-col{width:46px;border-radius:6px 6px 0 0;box-shadow:inset 0 0 0 1px rgba(0,0,0,.05)}
.rb-name{font-size:12.5px;color:var(--muted);margin-top:7px;white-space:nowrap}
.rb-pct{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;margin-top:1px}
/* 分组横条表 */
table.sa-break{font-size:13.5px;border-collapse:collapse;width:100%}
table.sa-break th{text-align:left;color:var(--muted);font-size:12px;padding:6px 8px;border-bottom:2px solid var(--line)}
table.sa-break td{padding:5px 8px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums;vertical-align:middle}
table.sa-break td.lbl{font-weight:700;white-space:nowrap}
/* 时间趋势折线（纯CSS柱） */
.trendbars{display:flex;align-items:flex-end;gap:10px;height:130px;padding:0 4px}
.tbar{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;min-width:52px}
.tbar .tstack{width:74%;display:flex;flex-direction:column-reverse;border-radius:5px 5px 0 0;overflow:hidden;min-height:3px}
.tbar .tseg{width:100%}
.tseg.s-hit{background:var(--soft-green)}
.tseg.s-part{background:#dfe3e8}
.tseg.s-miss{background:var(--soft-red)}
.tbar .tlabel{font-size:11px;color:var(--muted);margin-top:5px;white-space:nowrap}
.tbar .tval{font-size:12px;font-weight:800;font-variant-numeric:tabular-nums;margin-bottom:3px}
table.setupstats{font-size:14px;border-collapse:collapse;width:100%}
table.setupstats th{text-align:left;color:var(--muted);font-size:12.5px;padding:6px 9px;border-bottom:2px solid var(--line)}
table.setupstats td{padding:6px 9px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
.statsrow{display:grid;grid-template-columns:3fr 2fr;gap:12px}
@media(max-width:900px){.statsrow{grid-template-columns:1fr}}
.iconbtn{cursor:pointer;border:none;background:none;font-size:18px;padding:2px 6px;border-radius:6px}
.iconbtn:hover{background:#eef2f6}
.logic{font-size:15px;color:#374151;margin:8px 0 4px}
.logic b{color:var(--muted);font-size:12.5px;letter-spacing:.03em}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 12px}
.stat{border:1px solid var(--line);border-radius:10px;padding:7px 13px;background:#fafbfc}
.stat span{display:block;font-size:12px;color:var(--muted);font-weight:700}
.stat strong{font-size:17px;font-variant-numeric:tabular-nums}
.stat strong.up{color:var(--green)}.stat strong.dn{color:var(--red)}
table.mini{font-size:15px;margin:6px 0}
table.mini td,table.mini th{padding:7px 11px}
tr.leg-buy td:nth-child(2){color:var(--green);font-weight:700}
tr.leg-sell td:nth-child(2){color:var(--red);font-weight:700}
.score{display:inline-block;min-width:26px;text-align:center;border-radius:6px;font-weight:800;padding:1px 6px}
.s5,.s4{color:var(--green);background:var(--green-bg)}
.s3{color:var(--blue);background:var(--blue-bg)}
.s2,.s1{color:var(--red);background:var(--red-bg)}
.stophist{font-size:14px;color:#4b5563;background:#f8fafc;border-radius:10px;padding:8px 12px;margin:8px 0}
.stophist .cur{font-weight:800;color:var(--text)}
.stophist .old{color:var(--muted);text-decoration:line-through;margin-right:8px}
.review{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.rv{font-size:13px;border:1px dashed var(--line);border-radius:8px;padding:5px 10px}
.rv b{font-weight:800}
.rv.yes{border-style:solid;background:var(--red-bg);border-color:#eccabf}
.rv.good{border-style:solid;background:var(--green-bg);border-color:#bfe0cd}
.editform{background:#f8fafc;border:1px solid var(--line);border-radius:12px;padding:14px;margin:10px 0}
.editform .grid2{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.editform label{display:block;font-size:12.5px;font-weight:700;color:var(--muted);margin-bottom:3px}
.editform input,.editform select,.editform textarea{width:100%;box-sizing:border-box;font-size:15px;padding:7px 9px;
  border:1px solid #cfd6de;border-radius:8px;background:#fff;font-family:inherit}
.editform input.empty-field,.editform select.empty-field,.editform textarea.empty-field{
  border-color:#e2a493;background:var(--red-bg)}
.editform textarea{min-height:60px}
.editform .full{grid-column:1/-1}
.formbtns{display:flex;gap:8px;margin-top:12px}
.daysum{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin:14px 0}
.dshead{font-size:19px;font-weight:800;margin-bottom:8px;display:flex;align-items:center}
pre.dstext{white-space:pre-wrap;font-family:inherit;font-size:15px;line-height:1.65;margin:0 0 10px;background:#fafbfc;border-radius:10px;padding:11px 13px}
pre.dstext.vic{background:var(--blue-bg)}
.dslabel{font-size:12px;font-weight:800;color:var(--muted);letter-spacing:.05em;margin:8px 0 3px}
.dslabel{font-size:12px;font-weight:800;color:var(--muted);letter-spacing:.05em;margin:8px 0 3px}
/* KPI 条（2026-08-09 Vic：「持仓中、已平仓那几个标签不用那么大，设计成一整个标签吧」）——
   原来是5张独立卡片各带边框/阴影/23px大字，横着占掉一大块。改成**一条**：
   外层一个容器，内部各项靠竖线分隔，字号收到16px。信息一个没少，高度掉了一半多。 */
.kpis{display:flex;flex-wrap:wrap;align-items:stretch;margin:14px 0;
  background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--blue);
  border-radius:12px;box-shadow:0 4px 12px rgba(15,23,42,.04);overflow:hidden}
.kpi{padding:8px 18px;border-left:1px solid var(--line);flex:1 1 auto;min-width:96px}
.kpi:first-child{border-left:0}
.kpi span{display:block;font-size:11.5px;color:var(--muted);font-weight:700;white-space:nowrap}
.kpi strong{font-size:16px;font-variant-numeric:tabular-nums;line-height:1.35}
.kpi em{font-style:normal;font-size:11px;color:var(--muted);font-weight:600;margin-left:3px}
</style>
</head>
<body><main class="wrap">
<header>
  <h1>交易日志与执行复盘</h1>
  <p class="muted note"><a href="index.html">← 返回报告索引</a></p>
</header>
<div class="topbar">
  <button class="btn primary" onclick="saveFile()">💾 保存</button>
  <button class="btn" onclick="addTrade()">➕ 新交易</button>
  <button class="btn" onclick="exportJson()">⬇ 导出JSON备份</button>
  <div class="searchbox">🔍<input id="searchbox" placeholder="搜索代码/逻辑关键词…" oninput="onSearch(this.value)"></div>
  <span id="savestate"></span>
</div>
<div id="app"></div>
<footer class="source"><p>数据单一来源：data/tradebook.json。Claude的盘后脚本会保留你在这里做的所有修改。</p></footer>
</main>
<script>
const SETUPS = ["Momentum Burst","Episodic Pivot","Base Breakout","Pullback","No Setup"];
let state = __DATA__;
// 2026-07-28 Vic：「tradebook里面开一个新的标签页，继续setup A历史」——
// 数据源是 data/setup_track.json（Claude维护的Setup台账），构建时独立注入，
// **不写进 state / tradebook.json**，Vic自己的交易记录完全不受影响。
const SETUP_HISTORY = __SETUP_HISTORY__;
let editing = null;          // trade id 正在编辑
let dirty = false;
let activeTab = "open";      // open | closed | todo | summaries
let searchQuery = "";
let closedFilters = new Set();  // 已平仓筛选：daytrade/mentor/win/lose/sellfly/shakeout/breakdown
let expandedIds = new Set();    // 已平仓卡片默认折叠，点击展开的id集合
const EXIT_TAGS = ["板块转弱","fakeout","大市不好","减仓观望","setup failed"];
const ENTRY_TAGS = ["突破buy point","tight盘整","shakeout+LG","板块强势","回踩支撑","巨量","财报事件","日内突破"];

const $ = s => document.querySelector(s);
const esc = s => String(s==null?"":s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = v => { const x = parseFloat(v); return isNaN(x) ? null : x; };
const fmt = (x,d=2) => x==null ? "-" : x.toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const pct = x => x==null ? "" : (x>=0?"+":"")+x.toFixed(2)+"%";
function markDirty(){ dirty = true; $("#savestate").innerHTML = '<span class="dirty">● 有未保存修改</span>'; }

function calc(t){
  const buys = t.legs.filter(l=>l.action==="buy"), sells = t.legs.filter(l=>l.action==="sell");
  const kb = buys.filter(l=>l.price!=null), ks = sells.filter(l=>l.price!=null);
  const avgE = kb.length ? kb.reduce((a,l)=>a+l.qty*l.price,0)/kb.reduce((a,l)=>a+l.qty,0) : null;
  const openQty = buys.reduce((a,l)=>a+l.qty,0) - sells.reduce((a,l)=>a+l.qty,0);
  const realized = (avgE!=null && ks.length) ? ks.reduce((a,l)=>a+l.qty*(l.price-avgE),0) : null;
  const matched = ks.reduce((a,l)=>a+l.qty,0);
  const sh = t.stop_history||[];
  const stop0 = sh.length ? sh[0].stop : null;
  const curStop = sh.length ? sh[sh.length-1].stop : null;
  const riskPS = (avgE!=null && stop0!=null) ? avgE-stop0 : null;         // 初始风险（R的分母，全程不变）
  const riskCur = (avgE!=null && curStop!=null) ? avgE-curStop : null;    // 当前风险（随移动止损变化）
  const realizedR = (realized!=null && riskPS>0 && matched) ? (realized/matched)/riskPS : null;
  const rr0 = (t.target!=null && riskPS>0 && avgE!=null) ? (t.target-avgE)/riskPS : null;       // 初始R:R
  const rrCur = (t.target!=null && avgE!=null && riskCur!=null)
    ? (riskCur>0 ? (t.target-avgE)/riskCur : Infinity) : null;                                   // 当前R:R（止损上移后自动变）
  const realizedPct = (avgE && ks.length) ? (ks.reduce((a,l)=>a+l.qty*l.price,0)/matched/avgE-1)*100 : null;
  const incomplete = t.legs.some(l=>l.price==null);
  return {avgE, openQty, realized, realizedR, rr0, rrCur, riskPS, riskCur, realizedPct, incomplete, stop0, curStop};
}

function holdDays(t){
  const bd = t.legs.filter(l=>l.action==="buy"&&l.date).map(l=>l.date).sort()[0];
  if(!bd) return null;
  const end = t.status==="closed" ? (t.exit_date || t.legs.filter(l=>l.action==="sell"&&l.date).map(l=>l.date).sort().slice(-1)[0]) : new Date().toISOString().slice(0,10);
  if(!end) return null;
  return Math.max(0, Math.round((new Date(end)-new Date(bd))/86400000));
}

function scoreHtml(v){ return v==null ? '<span class="muted">-</span>' : '<span class="score s'+v+'">'+v+'</span>'; }
function rvChip(label, val, goodWhen){
  if(val==null) return '<span class="rv"><b>'+label+'</b>：未评</span>';
  const yes = val===true;
  const cls = (yes === goodWhen) ? "good" : "yes";
  return '<span class="rv '+cls+'"><b>'+label+'</b>：'+(yes?"是":"否")+'</span>';
}

function toggleExpand(id){ if(expandedIds.has(id)) expandedIds.delete(id); else expandedIds.add(id); render(); }
function collapsedRow(t, c){
  const oc = outcomeFromReview(t.review);
  const OC = {sell_fly:'卖飞', shakeout:'Shakeout/LG', breakdown:'突破向下', none:'', '':''};
  const mini = [];
  if(t.day_trade) mini.push('<span class="chip daytrade">日内</span>');
  if(t.mentor) mini.push('<span class="chip setup">👨‍🏫</span>');
  if(t.setup_type) mini.push('<span class="chip setup">'+esc(t.setup_type)+'</span>');
  if(OC[oc]) mini.push('<span class="chip '+(oc==='breakdown'?'planned':'unplanned')+'">'+OC[oc]+'</span>');
  const pnl = c.realized==null ? '<span class="pnl">—</span>'
    : '<span class="pnl '+(c.realized>0?'up':'dn')+'">'+(c.realized>=0?'+':'')+fmt(c.realized)
      +'（'+pct(c.realizedPct)+(c.realizedR!=null?'·'+(c.realizedR>=0?'+':'')+c.realizedR.toFixed(1)+'R':'')+'）</span>';
  return '<div class="trow" onclick="toggleExpand(\''+t.id+'\')">'
    +'<span class="dot '+(t.account==='moomoo'?'mm':'lb')+'"></span>'
    +'<span class="tk2">'+esc(t.ticker)+'</span>'
    +'<span class="dates">'+esc(t.entry_date||'—')+(t.exit_date&&t.exit_date!==t.entry_date?'→'+esc(t.exit_date.slice(5)):'')+'</span>'
    +pnl
    +'<span class="minichips">'+mini.join('')+'</span>'
    +'</div>';
}

function tradeCard(t){
  if(editing===t.id) return tradeForm(t);
  const c = calc(t);
  // v4: 已平仓默认折叠成一行摘要，点击展开（editing中的不折叠）
  if(t.status==="closed" && !expandedIds.has(t.id)) return collapsedRow(t, c);
  const hd = holdDays(t);
  const chips = [];
  if(t.setup_type) chips.push('<span class="chip setup">'+esc(t.setup_type)+'</span>');
  if((t.catalyst||"").trim()) chips.push('<span class="chip">催化：'+esc(t.catalyst)+'</span>');
  // 日内/跟老师的没有planned一说，只有自主非日内交易才显示
  if(!t.day_trade && !t.mentor){
    if(t.planned===true) chips.push('<span class="chip planned">Planned</span>');
    if(t.planned===false) chips.push('<span class="chip unplanned">Unplanned</span>');
  }
  (t.execution_flags||[]).forEach(f=>chips.push('<span class="chip unplanned">'+esc(f)+'</span>'));
  if(t.mentor) chips.push('<span class="chip setup">👨‍🏫 跟老师</span>');
  if(t.day_trade) chips.push('<span class="chip daytrade">日内</span>');
  // 复盘提醒：一周内不催（刚卖完看不出后续表现），第2周催，过了2周就闭嘴（补了也没参考价值）
  if(t.status==="closed" && !t.day_trade && outcomeFromReview(t.review)===""){
    const dsince = daysSinceExit(t);
    if(dsince!=null){
      if(reviewOverdue(t)) chips.push('<span class="chip hold-short">📝 该复盘了（已过'+dsince+'天）</span>');
      else if(dsince<=REVIEW_DUE_DAYS) chips.push('<span class="chip">复盘：'+REVIEW_DUE_DAYS+'天后再填</span>');
      else chips.push('<span class="chip">已过'+dsince+'天，复盘窗口关了</span>');
    }
  }
  chips.push('<span class="chip '+(t.status==="open"?"open":"closed")+'">'+(t.status==="open"?"持仓中":"已平仓")+'</span>');
  if(hd!=null) chips.push('<span class="chip'+(t.status==="closed"&&!t.day_trade&&hd<=2?' hold-short" title="持仓过短':'')+'">持仓'+hd+'天</span>');
  if(t.account) chips.push(t.account==="moomoo" ? '<span class="chip acct-mm">Moomoo</span>' : '<span class="chip acct-lb">LongBridge</span>');

  const stats = [];
  stats.push(['均价', fmt(c.avgE)]);
  if(c.stop0!=null) stats.push(['初始止损', fmt(c.stop0)]);
  if(c.curStop!=null && c.curStop!==c.stop0) stats.push(['当前止损', fmt(c.curStop)]);
  if(c.riskCur!=null && c.curStop!==c.stop0) stats.push(['当前风险/股', c.riskCur<=0?'0（保本止损）':fmt(c.riskCur)]);
  if(t.target!=null) stats.push(['目标价', fmt(t.target)]);
  // R:R 自动计算：初始R:R用初始止损，当前R:R随移动止损自动变
  if(c.rr0!=null) stats.push(['初始R:R', '1 : '+c.rr0.toFixed(1)]);
  if(c.rrCur!=null && c.curStop!==c.stop0) stats.push(['当前R:R', c.rrCur===Infinity?'∞（止损已过成本，零风险）':'1 : '+c.rrCur.toFixed(1)]);
  if(t.status==="open" && c.stop0==null) stats.push(['R:R', '填止损后自动显示']);
  if(t.status==="open") stats.push(['剩余股数', c.openQty]);
  if(c.realized!=null) stats.push(['已实现', (c.realized>=0?"+":"")+fmt(c.realized)+' USD（'+pct(c.realizedPct)+'）']);
  if(c.realizedR!=null) stats.push(['已实现R', (c.realizedR>=0?"+":"")+c.realizedR.toFixed(2)+'R']);
  if(t.execution_quality){
    const EQ = {clean:['按纪律','s4'], flawed:['有瑕疵','s3'], chaotic:['失控','s1']};
    const [lbl,cls] = EQ[t.execution_quality] || [t.execution_quality,''];
    stats.push(['执行质量', '<span class="score '+cls+'">'+lbl+'</span>']);
  }
  if(c.incomplete) stats.push(['⚠', '有成交价待补']);
  const statHtml = stats.map(([k,v])=>{
    const cls = (String(k).startsWith('已实现')&&c.realized!=null) ? (c.realized>0?'up':'dn') : '';
    return '<div class="stat"><span>'+esc(k)+'</span><strong class="'+cls+'">'+v+'</strong></div>';
  }).join('');

  const legRows = t.legs.map((l,i)=>'<tr class="leg-'+l.action+'"><td class="nowrap">'+esc(l.date||"—")+'</td><td class="nowrap">'
    +(l.action==="buy"?"买入":"卖出")+'</td><td class="num">'+l.qty+'</td><td class="num">'+(l.price==null?"待补":fmt(l.price))
    +'</td><td>'+esc(l.note||"")+'</td></tr>').join('');

  let stopHist = '';
  if(t.stop_history && t.stop_history.length){
    const parts = t.stop_history.map((s,i)=>{
      let riskTxt = '';
      if(c.avgE!=null && s.stop!=null){
        const abs = c.avgE - s.stop;
        const pct = c.avgE ? abs/c.avgE*100 : null;
        riskTxt = abs>=0
          ? '·风险'+fmt(abs)+'/'+pct.toFixed(1)+'%'
          : '·保本+'+fmt(-abs)+'/+'+(-pct).toFixed(1)+'%';
      }
      const label = fmt(s.stop)+'（'+esc(s.date||"—")+(s.note?'·'+esc(s.note):'')+riskTxt+'）';
      return i===t.stop_history.length-1 ? '<span class="cur">'+label+'</span>' : '<span class="old">'+label+'</span>';
    });
    stopHist = '<div class="stophist">🛡 止损轨迹：'+parts.join(' → ')+'</div>';
  }

  let review = '';
  if(t.status==="closed"){
    const outcome = outcomeFromReview(t.review);
    const OUTCOME_LABEL = {sell_fly:['卖飞了',"yes"], shakeout:['Shakeout/LG',"yes"], breakdown:['卖在突破向下（止损对了）',"good"], none:['都不是/正常出场',""], '':['未评',""]};
    const [olabel, ocls] = OUTCOME_LABEL[outcome];
    review = '<div class="review"><span class="rv'+(ocls?' '+ocls:'')+'"><b>卖后结果</b>：'+olabel+'</span>'
      + (outcome==='shakeout' ? rvChip('已追入', t.review.chase_reentry, true) : '')
      + (t.review.note ? '<span class="rv"><b>备注</b>：'+esc(t.review.note)+'</span>' : '')
      + '</div>';
  }

  return '<div class="trade"><div class="thead-line"><span class="tk">'+esc(t.ticker)+'</span>'+chips.join('')
    +'<span class="rowbtns">'
    +(t.status==="closed"?'<button class="iconbtn" title="折叠" onclick="toggleExpand(\''+t.id+'\')">🔼</button>':'')
    +'<button class="iconbtn" title="编辑" onclick="startEdit(\''+t.id+'\')">✏️</button>'
    +'<button class="iconbtn" title="删除" onclick="delTrade(\''+t.id+'\')">🗑️</button></span></div>'
    +(t.entry_logic?'<p class="logic"><b>买入逻辑</b>　'+esc(t.entry_logic)+'</p>':'')
    +(t.exit_logic?'<p class="logic"><b>卖出逻辑</b>　'+esc(t.exit_logic)+'</p>':'')
    +'<div class="stats">'+statHtml+'</div>'
    +stopHist
    +'<table class="mini"><thead><tr><th>日期</th><th>动作</th><th class="num">股数</th><th class="num">价格</th><th>执行笔记</th></tr></thead><tbody>'+legRows+'</tbody></table>'
    +review
    +'</div>';
}

function opt(v, cur){ return '<option value="'+esc(v)+'"'+(v===cur?' selected':'')+'>'+esc(v)+'</option>'; }
function triSel(name, val){
  return '<select id="'+name+'"><option value=""'+(val==null?' selected':'')+'>未评</option>'
    +'<option value="yes"'+(val===true?' selected':'')+'>是</option>'
    +'<option value="no"'+(val===false?' selected':'')+'>否</option></select>';
}

// 卖后结果互斥（2026-07-30 Vic反馈：卖飞/shakeout/突破向下这几个问题不会同时发生，
// undercut后追入了吗是shakeout的二阶追问，不该跟其它几个平级摆），改成单选+条件追问，
// 不再允许同一笔交易同时被标成"是shakeout"又"卖在突破向下"这种自相矛盾的组合。
const OUTCOME_OPTIONS = [['', '未评'], ['sell_fly','卖飞了（继续涨，卖早了）'],
  ['shakeout','是shakeout / liquidity grab（止损后价格收回）'],
  ['breakdown','卖在真突破向下（止损是对的，趋势延续下跌）'],
  ['none','都不是（正常止盈/其他原因平仓）']];
function outcomeFromReview(r){
  if(r.sell_fly===true) return 'sell_fly';
  if(r.undercut===true) return 'shakeout';
  if(r.breakdown_sell===true) return 'breakdown';
  if(r.sell_fly===false && r.undercut===false && r.breakdown_sell===false) return 'none';
  return '';
}
function outcomeSel(id, val){
  return '<select id="'+id+'">'+OUTCOME_OPTIONS.map(([v,label])=>
    '<option value="'+v+'"'+(v===val?' selected':'')+'>'+label+'</option>').join('')+'</select>';
}
function applyReviewOutcome(t){
  if(!$("#f_rv_outcome")) return;
  const v = $("#f_rv_outcome").value;
  const map = {sell_fly:[true,false,false], shakeout:[false,true,false], breakdown:[false,false,true], none:[false,false,false]};
  const [sell_fly, undercut, breakdown_sell] = map[v] || [null,null,null];
  t.review.sell_fly = sell_fly;
  t.review.undercut = undercut;
  t.review.breakdown_sell = breakdown_sell;
  t.review.chase_reentry = (v==='shakeout' && $("#f_rv_re")) ? readTri("f_rv_re") : (v==='shakeout' ? t.review.chase_reentry : null);
  if($("#f_rv_note")) t.review.note = $("#f_rv_note").value;
}
function onOutcomeChange(id){ commitFormLight(id); const t = state.trades.find(x=>x.id===id); applyReviewOutcome(t); render(); }

function tradeForm(t){
  // 日内交易只输一次日期（2026-07-09 Vic要求）：勾选日内后legs不再逐条填日期，统一用交易日期
  const dt = t.day_trade;
  const mentor = t.mentor;
  const tradeDate = (t.legs.find(l=>l.date)||{}).date || new Date().toISOString().slice(0,10);
  // 建仓日期＝第一笔买入日期（日内则用统一交易日期），下面初始止损日期直接读这个值，不用重复填
  const entryDate = dt ? tradeDate : ((t.legs.find(l=>l.action==="buy"&&l.date)||{}).date || tradeDate);
  const legRows = t.legs.map((l,i)=>'<tr>'
    +(dt ? '' : '<td><input type="date" style="width:150px" id="lg_d_'+i+'" value="'+esc(l.date||"")+'"></td>')
    +'<td><select id="lg_a_'+i+'">'+opt("buy",l.action)+opt("sell",l.action)+'</select></td>'
    +'<td><input style="width:70px" id="lg_q_'+i+'" value="'+(l.qty??"")+'"></td>'
    +'<td><input style="width:90px" id="lg_p_'+i+'" value="'+(l.price??"")+'"></td>'
    +'<td><input id="lg_n_'+i+'" value="'+esc(l.note||"")+'"></td>'
    +'<td><button class="btn small danger" onclick="delLeg(\''+t.id+'\','+i+')">🗑️</button></td></tr>').join('');
  const stopRows = (t.stop_history||[]).map((s,i)=>'<tr>'
    +(i===0
      ? '<td>'+esc(entryDate)+'</td>'
      : '<td><input type="date" style="width:150px" id="st_d_'+i+'" value="'+esc(s.date||"")+'"></td>')
    +'<td><input style="width:90px" id="st_s_'+i+'" value="'+(s.stop??"")+'"></td>'
    +'<td><input id="st_n_'+i+'" value="'+esc(s.note||"")+'"></td>'
    +'<td>'+(i===0?'':'<button class="btn small danger" onclick="delStop(\''+t.id+'\','+i+')">🗑️</button>')+'</td></tr>').join('');
  const exitTags = '<div class="tagbtns">'+EXIT_TAGS.map(tag=>'<span class="tagbtn" onclick="addExitTag(\''+t.id+'\',\''+tag+'\')">+ '+esc(tag)+'</span>').join('')+'</div>';
  const entryTags = '<div class="tagbtns">'+ENTRY_TAGS.map(tag=>'<span class="tagbtn" onclick="addEntryTag(\''+t.id+'\',\''+tag+'\')">+ '+esc(tag)+'</span>').join('')+'</div>';
  // 日内 / 跟老师的：不写买卖逻辑，也不评执行质量、不做卖后复盘（2026-08-07 Vic：日内不追踪，只写执行笔记）
  const noLogic = dt || mentor;
  const noReview = dt;
  // 顶部字段全部改成等高控件（输入框/分段按钮/下拉），不再混裸checkbox——
  // 2026-08-08 Vic："又有方块又有下拉框，都不对齐"
  const seg = (opts, cur, onclickFn) => '<div class="seg">'+opts.map(([v,l])=>
    '<button type="button" class="segbtn'+(v===cur?' on':'')+'" onclick="'+onclickFn+'(\''+t.id+'\',\''+v+'\')">'+esc(l)+'</button>').join('')+'</div>';
  const tog = (on, label, fn) => '<button type="button" class="segbtn tog'+(on?' on':'')+'" onclick="'+fn+'(\''+t.id+'\')">'+esc(label)+'</button>';
  const marks = '<div class="seg">'+tog(dt,'日内','toggleDT')+tog(mentor,'跟单','toggleMentor')
    +(noLogic?'':tog(t.planned===true,'Planned','togglePlanned'))+'</div>';
  return '<div class="trade"><div class="editform">'
    +'<div class="frow">'
    +'<div class="fld grow"><label>Ticker</label><input id="f_ticker" value="'+esc(t.ticker)+'"></div>'
    +'<div class="fld"><label>账户</label>'+seg([["moomoo","moomoo"],["longbridge","LongBridge"]], t.account, "setAccount")+'</div>'
    +'<div class="fld"><label>标记</label>'+marks+'</div>'
    +(dt ? '<div class="fld"><label>交易日期</label><input type="date" id="f_tradedate" value="'+esc(tradeDate)+'"></div>' : '')
    +(dt ? '' : '<div class="fld grow"><label>Setup类型</label><select id="f_setup" onchange="onSetupChange(\''+t.id+'\')"><option value=""'+(t.setup_type==null?' selected':'')+'>-</option>'+SETUPS.map(s=>opt(s,t.setup_type)).join('')+'</select></div>')
    +'</div>'
    +'<div class="dslabel">LEGS</div>'
    +'<table class="mini"><thead><tr>'+(dt?'':'<th>日期</th>')+'<th>动作</th><th>股数</th><th>价格</th><th>执行笔记</th><th></th></tr></thead><tbody>'+legRows+'</tbody></table>'
    +'<button class="btn small" onclick="addLeg(\''+t.id+'\')">➕ 加一笔</button>'
    // 买卖逻辑挪到legs之后——填完成交明细再回头写当时怎么想的（2026-08-08 Vic要求的顺序）
    +(noLogic ? '' : '<div class="grid2" style="margin-top:12px">'
      +'<div class="full"><label>买入逻辑</label><textarea id="f_entry_logic">'+esc(t.entry_logic||"")+'</textarea>'+entryTags+'</div>'
      +'<div class="full"><label>卖出逻辑</label><textarea id="f_exit_logic">'+esc(t.exit_logic||"")+'</textarea>'+exitTags+'</div>'
      +'</div>')
    +(mentor ? '' : execQualityBlock(t))
    // 日内不写止损（2026-08-09 Vic：「日内不要记录止损了，没用的吧」）——当天进出，
    // 止损位不构成过夜风险边界、R 也算不出有意义的值。整块隐藏，连同必填红框一起免掉。
    // 旧数据里已有的 stop_history 不删，只是不显示；取消日内勾选后会重新出现。
    +(dt ? '' :
      '<div class="dslabel" style="margin-top:12px">止损轨迹</div>'
      +'<table class="mini"><thead><tr><th>日期</th><th>止损价</th><th>备注</th><th></th></tr></thead><tbody>'+stopRows+'</tbody></table>'
      +'<button class="btn small" onclick="addStop(\''+t.id+'\')">➕ 改止损</button>')
    +(noReview ? '' : reviewBlock(t))
    +'<div class="formbtns"><button class="btn primary" onclick="commitEdit(\''+t.id+'\')">✔ 完成</button>'
    +'<button class="btn" onclick="cancelEdit()">取消</button></div>'
    +'</div></div>';
}

// 复盘（2026-08-08合并：原来"卖后复盘"标题下面还有个"卖后结果"标签，同一件事写了两行，Vic抓到了）。
// 复盘周期：Vic定"3天/1周/2周，过了2周任何复盘数据就没有意义了"。
const REVIEW_WINDOWS = [["3d","3天"],["1w","1周"],["2w","2周"]];
function reviewBlock(t){
  const oc = outcomeFromReview(t.review);
  const win = t.review.window || "";
  const winSeg = '<div class="seg">'+REVIEW_WINDOWS.map(([v,l])=>
    '<button type="button" class="segbtn'+(v===win?' on':'')+'" onclick="setReviewWindow(\''+t.id+'\',\''+v+'\')">'+l+'</button>').join('')+'</div>';
  return '<div class="dslabel" style="margin-top:12px">复盘</div>'
    +'<div class="frow">'
    +'<div class="fld"><label>复盘周期</label>'+winSeg+'</div>'
    +'<div class="fld grow"><label>结果</label>'
      +outcomeSel("f_rv_outcome", oc).replace('<select', '<select onchange="onOutcomeChange(\''+t.id+'\')"')+'</div>'
    +(oc==='shakeout' ? '<div class="fld"><label>之后追入了吗</label>'+triSel("f_rv_re", t.review.chase_reentry)+'</div>' : '')
    +'<div class="fld grow"><label>备注</label><input id="f_rv_note" value="'+esc(t.review.note||"")+'"></div>'
    +'</div>';
}
function setReviewWindow(id, w){
  commitFormLight(id);
  const t = state.trades.find(x=>x.id===id);
  t.review.window = (t.review.window===w) ? null : w;   // 再点一次取消
  markDirty(); render();
}
function setAccount(id, acct){ commitFormLight(id); const t=state.trades.find(x=>x.id===id);
  t.account = acct; markDirty(); render(); }
function togglePlanned(id){ commitFormLight(id); const t=state.trades.find(x=>x.id===id);
  t.planned = !(t.planned===true); markDirty(); render(); }

// 执行质量：3档 + 问题标签。**刻意跟盈亏解耦**——
// 2026-08-07 Vic："很多我不知道怎么评12345，我都写了3…基本上亏钱就是1，赚钱就是5，我觉得这个逻辑上要改的"。
// 他说得对：1-5分退化成盈亏的复读机就没有复盘价值了。执行质量问的是"这笔操作是否照纪律做"，
// 跟结果无关——按计划执行但亏钱是好交易（该重复），乱做但赚钱是坏习惯（该警惕）。
// 所以改成一个可判断的问题："入场/止损/出场有没有按计划走？"，再点几个具体犯了什么错的标签。
const EXEC_FLAGS = ["追高进场","没设止损","挪了止损","提前恐慌砍","破位不砍","乱加仓","计划外交易","看别人喊单进"];
const EXEC_QUALITIES = [["clean","按纪律","q-good"],["flawed","有瑕疵","q-mid"],["chaotic","失控","q-bad"]];
// 当时的状态（2026-08-09 Vic：「执行质量失控里面，增加让我填的地方，比如 wolf 我就是在
// 没自信的状态下交易了拿不住」）。EXEC_FLAGS 记的是**做错了什么动作**，这里记的是
// **当时人是什么状态**——同一个动作（提前砍）背后可能是没信心、也可能是刚亏完想扳回来，
// 后续要分开统计才知道该修哪一头。预设标签点一下就好，右边文本框写具体的。
const EXEC_STATES = ["没信心/拿不住","刚亏完想扳回","怕错过FOMO","盯盘太久累了",
                     "被别人观点影响","对这只不熟","仓位太重睡不着","赌财报/消息"];
function execQualityBlock(t){
  const q = t.execution_quality || "";
  const flags = t.execution_flags || [];
  // 三个标签直接摊开，点一次就好（2026-08-08 Vic："展开3个标签让我选，这样我只要选择一次"）
  const chips = '<div class="qchips">'+EXEC_QUALITIES.map(([v,l,cls])=>
    '<button type="button" class="qchip '+cls+(v===q?' on':'')+'" onclick="setExecQ(\''+t.id+'\',\''+v+'\')">'+l+'</button>').join('')+'</div>';
  const states = t.execution_states || [];
  const LAB = 'style="display:block;font-size:12.5px;font-weight:700;color:var(--muted);margin-bottom:4px"';
  const tagBtns = (q==="flawed"||q==="chaotic")
    ? '<div style="margin-top:9px"><label '+LAB+'>具体犯了什么（动作）</label>'
      + '<div class="tagbtns">'+EXEC_FLAGS.map(f=>'<span class="tagbtn'+(flags.includes(f)?' on':'')+'" onclick="toggleExecFlag(\''+t.id+'\',\''+f+'\')">'+(flags.includes(f)?'✓ ':'+ ')+esc(f)+'</span>').join('')+'</div></div>'
      // 状态区：动作记"做错了什么"，这里记"当时人是什么状态"——两者要分开才统计得出该修哪一头
      + '<div style="margin-top:11px"><label '+LAB+'>当时的状态（为什么会这样）</label>'
      + '<div class="tagbtns">'+EXEC_STATES.map(f=>'<span class="tagbtn'+(states.includes(f)?' on':'')+'" onclick="toggleExecState(\''+t.id+'\',\''+f+'\')">'+(states.includes(f)?'✓ ':'+ ')+esc(f)+'</span>').join('')+'</div>'
      + '<textarea id="f_exec_note" placeholder="具体点：当时在想什么、身体/情绪状态、外部干扰……（可留空）" '
      + 'style="width:100%;box-sizing:border-box;margin-top:7px;min-height:52px;font-size:14.5px;padding:7px 9px;border:1px solid #cfd6de;border-radius:8px;font-family:inherit">'
      + esc(t.execution_note||"") + '</textarea></div>'
    : '';
  return '<div class="dslabel" style="margin-top:12px">执行质量</div>'
    + '<div class="execblock">'+chips+tagBtns+'</div>';
}
function toggleExecState(id, f){
  commitFormLight(id);
  const t = state.trades.find(x=>x.id===id);
  t.execution_states = t.execution_states || [];
  const i = t.execution_states.indexOf(f);
  if(i>=0) t.execution_states.splice(i,1); else t.execution_states.push(f);
  markDirty(); render();
}
function setExecQ(id, v){
  commitFormLight(id);
  const t = state.trades.find(x=>x.id===id);
  t.execution_quality = (t.execution_quality===v) ? null : v;   // 再点一次取消
  if(t.execution_quality!=="flawed" && t.execution_quality!=="chaotic") t.execution_flags = [];
  markDirty(); render();
}
function toggleExecFlag(id, f){
  commitFormLight(id);
  const t = state.trades.find(x=>x.id===id);
  t.execution_flags = t.execution_flags || [];
  const i = t.execution_flags.indexOf(f);
  if(i>=0) t.execution_flags.splice(i,1); else t.execution_flags.push(f);
  markDirty(); render();
}
function onSetupChange(id){ commitFormLight(id); const t = state.trades.find(x=>x.id===id);
  t.setup_type = $("#f_setup").value || null; markDirty(); render(); }

function readTri(id){ const v = $("#"+id).value; return v==="yes" ? true : (v==="no" ? false : null); }

function commitEdit(id){
  const t = state.trades.find(x=>x.id===id);
  // 账户/日内/跟单/Planned 现在是分段按钮，点的时候就已经写进state了，这里不用再从DOM读
  const dtDate = t.day_trade && $("#f_tradedate") ? ($("#f_tradedate").value||null) : null;
  t.legs.forEach((l,i)=>{
    l.date = t.day_trade ? dtDate : ($("#lg_d_"+i) ? ($("#lg_d_"+i).value||null) : l.date);
    l.action = $("#lg_a_"+i).value;
    l.qty = num($("#lg_q_"+i).value) || 0;
    l.price = num($("#lg_p_"+i).value);
    l.note = $("#lg_n_"+i).value;
  });
  // 建仓日期＝第一笔买入日期（日内用统一交易日期），初始止损日期自动同步，不用重复填
  const entryDate = t.day_trade ? dtDate : ((t.legs.find(l=>l.action==="buy"&&l.date)||{}).date || null);
  (t.stop_history||[]).forEach((s,i)=>{
    s.date = (i===0) ? (entryDate || s.date) : (($("#st_d_"+i) ? $("#st_d_"+i).value : s.date) || null);
    s.stop = num($("#st_s_"+i).value);
    s.note = $("#st_n_"+i).value;
  });
  t.stop_history = (t.stop_history||[]).filter(s=>s.stop!=null);  // 没填数字的占位行自动清掉
  t.ticker = $("#f_ticker").value.trim().toUpperCase();
  t.setup_type = $("#f_setup") ? ($("#f_setup").value || null) : t.setup_type;
  // 日内/跟单没有planned一说，字段留null
  if(t.day_trade || t.mentor) t.planned = null;
  t.entry_logic = $("#f_entry_logic") ? $("#f_entry_logic").value : t.entry_logic;
  t.exit_logic = $("#f_exit_logic") ? $("#f_exit_logic").value : t.exit_logic;
  t.execution_note = $("#f_exec_note") ? $("#f_exec_note").value : t.execution_note;
  t.entry_date = entryDate || t.entry_date;
  // 日内不做复盘（Vic：日内不追踪），清掉免得挂在"待补齐"里
  if(t.day_trade){ t.review = {sell_fly:null,undercut:null,chase_reentry:null,breakdown_sell:null,note:t.review.note||"",window:null}; }
  else applyReviewOutcome(t);
  autoStatus(t);
  editing = null; markDirty(); render();
}
function autoStatus(t){
  // 平仓自动判定：没有剩余股数=closed，平仓日=最后一笔卖出日
  const buys = t.legs.filter(l=>l.action==="buy").reduce((a,l)=>a+l.qty,0);
  const sells = t.legs.filter(l=>l.action==="sell").reduce((a,l)=>a+l.qty,0);
  if(t.legs.length && buys-sells<=0){
    t.status = "closed";
    const sd = t.legs.filter(l=>l.action==="sell"&&l.date).map(l=>l.date).sort();
    if(sd.length) t.exit_date = sd[sd.length-1];
  } else { t.status = "open"; t.exit_date = null; }
}
function startEdit(id){
  editing = id;
  const t = state.trades.find(x=>x.id===id);
  // 初始止损必填：进编辑态时若没有止损记录，直接展开一条待填的初始止损行（不用再点"改止损"）
  if(t && (!t.stop_history || !t.stop_history.length)){
    t.stop_history = [{date: t.entry_date || new Date().toISOString().slice(0,10), stop: null, note: "初始止损"}];
  }
  render();
}
function cancelEdit(){ editing = null; render(); }
function toggleDT(id){ commitFormLight(id); const t = state.trades.find(x=>x.id===id);
  t.day_trade = !t.day_trade; if(t.day_trade) t.planned = null; markDirty(); render(); }
function toggleMentor(id){ commitFormLight(id); const t = state.trades.find(x=>x.id===id);
  t.mentor = !t.mentor; if(t.mentor) t.planned = null; markDirty(); render(); }
function addExitTag(id, tag){
  commitFormLight(id);
  const t = state.trades.find(x=>x.id===id);
  const tags = (t.exit_logic||"").split(/[;；,，]\s*/).map(s=>s.trim()).filter(Boolean);
  if(!tags.includes(tag)) tags.push(tag);
  t.exit_logic = tags.join('；');
  render();
}
function addEntryTag(id, tag){
  commitFormLight(id);
  const t = state.trades.find(x=>x.id===id);
  const tags = (t.entry_logic||"").split(/[;；,，]\s*/).map(s=>s.trim()).filter(Boolean);
  if(!tags.includes(tag)) tags.push(tag);
  t.entry_logic = tags.join('；');
  render();
}
function delTrade(id){ if(confirm("确认删除这笔交易？")){ state.trades = state.trades.filter(t=>t.id!==id); markDirty(); render(); } }
function addLeg(id){ commitFormLight(id); const t = state.trades.find(x=>x.id===id);
  t.legs.push({date:new Date().toISOString().slice(0,10), action:"sell", qty:0, price:null, decision_score:null, note:""}); render(); }
function delLeg(id,i){ commitFormLight(id); const t = state.trades.find(x=>x.id===id); t.legs.splice(i,1); markDirty(); render(); }
function addStop(id){ commitFormLight(id); const t = state.trades.find(x=>x.id===id);
  t.stop_history = t.stop_history||[]; t.stop_history.push({date:new Date().toISOString().slice(0,10), stop:null, note:""}); render(); }
function delStop(id,i){ commitFormLight(id); const t = state.trades.find(x=>x.id===id); t.stop_history.splice(i,1); markDirty(); render(); }
function commitFormLight(id){
  // 在编辑态点加行/删行前，先把当前输入吸进state，避免丢失（跟老师的交易/日内交易会隐藏部分字段，逐个判断存在再读，避免报错中断）
  const t = state.trades.find(x=>x.id===id);
  if(editing!==id || !$("#f_ticker")) return;
  try{
    t.legs.forEach((l,i)=>{
      if($("#lg_d_"+i)) l.date=$("#lg_d_"+i).value||null;
      if($("#lg_a_"+i)){ l.action=$("#lg_a_"+i).value; l.qty=num($("#lg_q_"+i).value)||0; l.price=num($("#lg_p_"+i).value); l.note=$("#lg_n_"+i).value; }
    });
    (t.stop_history||[]).forEach((s,i)=>{
      if(i>0 && $("#st_d_"+i)) s.date=$("#st_d_"+i).value||null;
      if($("#st_s_"+i)){ s.stop=num($("#st_s_"+i).value); s.note=$("#st_n_"+i).value; }
    });
    if($("#f_ticker")) t.ticker=$("#f_ticker").value;
    if($("#f_entry_logic")) t.entry_logic=$("#f_entry_logic").value;
    if($("#f_exit_logic")) t.exit_logic=$("#f_exit_logic").value;
    if($("#f_exec_note")) t.execution_note=$("#f_exec_note").value;
    if($("#f_setup")) t.setup_type=$("#f_setup").value||null;
    if(!t.day_trade) applyReviewOutcome(t);
  }catch(e){}
}
function addTrade(){
  const id = "NEW-"+Date.now();
  const today = new Date().toISOString().slice(0,10);
  state.trades.unshift({id, ticker:"", account:"moomoo", status:"open", entry_date:today, exit_date:null,
    setup_type:null, planned:false, day_trade:false, mentor:false, stop_initial:null, target:null,
    thesis:"", entry_logic:"", exit_logic:"",
    stop_history:[{date:today, stop:null, note:"初始止损"}],
    legs:[{date:today, action:"buy", qty:0, price:null, decision_score:null, note:""}],
    review:{sell_fly:null,undercut:null,chase_reentry:null,breakdown_sell:null,note:""},
    execution_grade:null, execution_score:null, execution_quality:null, execution_flags:[]});
  editing = id; activeTab = "open"; markDirty(); render();
}

// 每周复盘（2026-08-08 Vic：先要"每日给我一行输入就行"，随后改成"每日一句改每周复盘，
// 我没写的日子过了3天就删除，反正我也忘记了"）。所以：一周一行，空着的周过了3天就不再列出来，
// 只留本周 + 真正写过字的周；早期按天写过的几条老记录各自单独一行保住不丢。
// 原来这页是Claude的盘后总结全文 + Vic的长文本框 + 执行评分/最大失误/最好决策三个字段——
// Vic说"这个页面我不看的"，所以整块砍成一行输入。老数据（含他手写过的4条）保留在json里不删。
function dailyLineRows(){
  const byDate = {};
  (state.daily_summaries||[]).forEach(s=>{ byDate[s.date] = s; });
  const iso = d => d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  // 本周一
  const thisMon = new Date(today); thisMon.setDate(today.getDate() - ((today.getDay()+6)%7));
  const rows = [];
  // 最近12周，每周一行（周一为起点）
  for(let i=0;i<12;i++){
    const mon = new Date(thisMon); mon.setDate(thisMon.getDate() - i*7);
    const sun = new Date(mon);     sun.setDate(mon.getDate() + 6);
    const key = iso(mon);
    const s = byDate[key];
    const hasText = !!(s && s.vic_summary && s.vic_summary.trim());
    const hasSummary = !!(s && s.summary_kind==='weekly' && s.summary && s.summary.trim());
    // 空着的周（我也没写周报、他也没写字）：过了3天就不再列出来
    // （Vic："我没写的日子过了3天就删除，反正我也忘记了"）
    const daysSinceWeekEnd = Math.round((today - sun)/86400000);
    if(!hasText && !hasSummary && daysSinceWeekEnd > 3) continue;
    rows.push({date:key, s, label: (iso(mon).slice(5))+' ~ '+(iso(sun).slice(5))});
  }
  // 老的按天写过的记录（07月那几条手写复盘）不丢，各自单独一行显示
  Object.keys(byDate).forEach(d=>{
    const s = byDate[d];
    if(!(s.vic_summary && s.vic_summary.trim())) return;
    if(rows.some(r=>r.date===d)) return;
    rows.push({date:d, s, label:d.slice(5)});
  });
  return rows.sort((a,b)=>b.date.localeCompare(a.date));
}
// 渲染Claude的周报总结：第一行标题、第二行副标题、后面每个"• 小标题 + 正文"一块。
// **加粗只认 **文字**，其余一律escape**——数据是我自己生成的，但仍旧走转义，不给注入留口子。
function renderWeekly(txt){
  if(!txt || !txt.trim()) return '';
  const bold = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  const blocks = String(txt).split(/\n\n+/);
  let out = '';
  blocks.forEach((b,i)=>{
    const t = b.trim();
    if(!t) return;
    if(i===0){ out += '<div class="wk-title">'+bold(t)+'</div>'; return; }
    if(i===1 && !t.startsWith('•')){ out += '<div class="wk-sub">'+bold(t)+'</div>'; return; }
    const [head, ...rest] = t.replace(/^•\s*/,'').split('\n');
    out += '<div class="wk-pt"><div class="wk-pth">'+bold(head)+'</div>'
        + (rest.length? '<div class="wk-ptb">'+bold(rest.join('\n'))+'</div>' : '') + '</div>';
  });
  return '<div class="wk-body">'+out+'</div>';
}
function setDailyLine(date, val){
  let s = (state.daily_summaries||[]).find(x=>x.date===date);
  if(!s){
    s = {date, summary:null, vic_summary:null, vic_grade:null,
         vic_biggest_mistake:null, vic_best_decision:null};
    state.daily_summaries.push(s);
    state.daily_summaries.sort((a,b)=>b.date.localeCompare(a.date));
  }
  s.vic_summary = val.trim() || null;
  markDirty();   // 不render——保持输入焦点
}

const CLOSED_FILTERS = [["daytrade","日内"],["mentor","跟老师的"],["win","盈利的"],["lose","亏损的"],
  ["sellfly","卖飞的"],["shakeout","被shakeout"],["breakdown","突破向下"]];

function matchesSearch(t){
  if(!searchQuery) return true;
  const q = searchQuery.toLowerCase();
  return (t.ticker||"").toLowerCase().includes(q)
    || (t.entry_logic||"").toLowerCase().includes(q)
    || (t.exit_logic||"").toLowerCase().includes(q)
    || (t.setup_type||"").toLowerCase().includes(q);
}
function matchesClosedFilters(t, c){
  for(const f of closedFilters){
    if(f==="daytrade" && !t.day_trade) return false;
    if(f==="mentor" && !t.mentor) return false;
    if(f==="win" && !(c.realized>0)) return false;
    if(f==="lose" && !(c.realized<0)) return false;
    if(f==="sellfly" && t.review.sell_fly!==true) return false;
    if(f==="shakeout" && t.review.undercut!==true) return false;
    if(f==="breakdown" && t.review.breakdown_sell!==true) return false;
  }
  return true;
}
function onSearch(v){ searchQuery = v; render(); }
function setTab(tab){ activeTab = tab; render(); }
function toggleFilter(f){ if(closedFilters.has(f)) closedFilters.delete(f); else closedFilters.add(f); render(); }

// v4: 待补齐——已平仓但主观字段还缺的交易（日内不要求setup，mentor不要求逻辑/执行分）
// 平仓至今天数（没有平仓日就返回null）。
// 按"日历天"算：exit_date只有日期没有时分，直接跟当前时刻相减会把今天平的仓算成1天、
// 把整14天算成15天（取决于现在几点），边界会飘。两边都归一到本地零点再减就稳定了。
function daysSinceExit(t){
  if(!t.exit_date) return null;
  const [y,m,d] = t.exit_date.split('-').map(Number);
  const exit = new Date(y, m-1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((today - exit)/86400000);
}
const REVIEW_DUE_DAYS = 7;    // 复盘宽限期：一周内不催（2026-08-07 Vic）
const REVIEW_DEAD_DAYS = 14;  // 超过两周就不再催了——Vic："过了2周任何复盘数据就没有意义了"
function reviewOverdue(t){
  // 日内不做复盘（Vic：日内不追踪），永远不算欠账
  if(t.day_trade || t.status!=="closed" || outcomeFromReview(t.review)!=="") return false;
  const d = daysSinceExit(t);
  // 只在 7 < 天数 ≤ 14 的窗口里催；超过两周补的复盘已经没有参考价值，硬挂在待补齐只是制造焦虑
  return d!=null && d > REVIEW_DUE_DAYS && d <= REVIEW_DEAD_DAYS;
}
function todoMissing(t){
  const miss = [];
  if(t.status!=="closed") return miss;
  if(!t.day_trade && !t.setup_type) miss.push("setup");
  // 日内和跟老师的都不写买卖逻辑（日内：Vic"没有买入逻辑和卖出逻辑，只写执行笔记"）
  if(!t.day_trade && !t.mentor && !(t.entry_logic||"").trim()) miss.push("买入逻辑");
  if(!t.mentor && !t.execution_quality) miss.push("执行质量");
  // 卖后结果不再是"平仓即欠账"——刚卖完还看不出后续表现，一周后才提醒（Vic："卖了之后表现不再必填，
  // 超过一周的提醒我填写"）。所以只有过了宽限期还空着才算missing。
  if(reviewOverdue(t)) miss.push("卖后复盘(已过"+daysSinceExit(t)+"天)");
  return miss;
}
function updateTodoField(id, field, value){
  const t = state.trades.find(x=>x.id===id);
  if(!t) return;
  if(field==="setup") t.setup_type = value||null;
  else if(field==="execq"){ t.execution_quality = value||null; if(value==="clean"||!value) t.execution_flags=[]; }
  else if(field==="entry") t.entry_logic = value;
  else if(field==="outcome"){
    const map = {sell_fly:[true,false,false], shakeout:[false,true,false], breakdown:[false,false,true], none:[false,false,false]};
    const [a,b,c] = map[value] || [null,null,null];
    t.review.sell_fly=a; t.review.undercut=b; t.review.breakdown_sell=c;
    if(value!=='shakeout') t.review.chase_reentry=null;
  }
  markDirty();
  // 不整页render——行内编辑保持焦点；只刷新tab计数和该行缺失标记由下次render处理
}
function todoRow(t){
  const c = calc(t);
  const miss = todoMissing(t);
  const pnl = c.realized==null?'—':((c.realized>=0?'+':'')+fmt(c.realized));
  return '<tr>'
    +'<td><b>'+esc(t.ticker)+'</b><br><span class="muted" style="font-size:11.5px">'+esc(t.exit_date||t.entry_date||'')+'</span></td>'
    +'<td class="'+(c.realized>0?'up':(c.realized<0?'dn':''))+'" style="font-variant-numeric:tabular-nums;font-weight:700">'+pnl+'</td>'
    +(t.day_trade ? '<td class="muted">日内</td>'
      : '<td><select onchange="updateTodoField(\''+t.id+'\',\'setup\',this.value)"><option value=""'+(t.setup_type==null?' selected':'')+'>-</option>'+SETUPS.map(s=>opt(s,t.setup_type)).join('')+'</select></td>')
    +((t.mentor||t.day_trade) ? '<td class="muted">'+(t.mentor?'跟老师':'日内')+'</td>'
      : '<td><input placeholder="标签/短语" value="'+esc(t.entry_logic||"")+'" onchange="updateTodoField(\''+t.id+'\',\'entry\',this.value)"></td>')
    +(t.mentor ? '<td class="muted">—</td>'
      : '<td><select onchange="updateTodoField(\''+t.id+'\',\'execq\',this.value)">'
        +[["","-"],["clean","按纪律"],["flawed","有瑕疵"],["chaotic","失控"]]
          .map(([v,l])=>'<option value="'+v+'"'+((t.execution_quality||"")===v?' selected':'')+'>'+l+'</option>').join('')
        +'</select></td>')
    +(t.day_trade ? '<td class="muted">不追踪</td>'
      : '<td>'+outcomeSel('todo_oc_'+t.id, outcomeFromReview(t.review)).replace('<select','<select onchange="updateTodoField(\''+t.id+'\',\'outcome\',this.value)"')+'</td>')
    +'<td class="miss">'+miss.join('、')+'</td>'
    +'<td><button class="iconbtn" title="展开完整编辑（就地展开，不跳走）" onclick="startEdit(\''+t.id+'\')">✏️</button></td>'
    +'</tr>';
}

// v4: 月度盈亏柱状图（纯CSS bar，不引外部库）+ 按setup类型胜率分解
function monthlyChart(done){
  const byMonth = {};
  done.forEach(x=>{
    const m = (x.t.exit_date||x.t.entry_date||'').slice(0,7);
    if(!m) return;
    byMonth[m] = (byMonth[m]||0) + x.c.realized;
  });
  const months = Object.keys(byMonth).sort();
  if(!months.length) return '';
  const maxAbs = Math.max(...months.map(m=>Math.abs(byMonth[m])), 1);
  const bars = months.map(m=>{
    const v = byMonth[m];
    const h = Math.max(Math.round(Math.abs(v)/maxAbs*80), 2);
    return '<div class="mbar"><span class="mval '+(v>=0?'up':'dn')+'">'+(v>=0?'+':'')+Math.round(v)+'</span>'
      +'<div class="bar '+(v>=0?'up':'dn')+'" style="height:'+h+'px"></div>'
      +'<span class="mlabel">'+m.slice(2)+'</span></div>';
  }).join('');
  return '<div class="statsblock"><h3>月度已实现盈亏（USD）</h3><div class="mbars">'+bars+'</div></div>';
}
function setupBreakdown(done){
  const by = {};
  done.forEach(x=>{
    const k = x.t.day_trade ? '日内' : (x.t.setup_type || '未标注');
    (by[k] = by[k]||[]).push(x);
  });
  const rows = Object.entries(by).sort((a,b)=>b[1].length-a[1].length).map(([k,xs])=>{
    const wins = xs.filter(x=>x.c.realized>0).length;
    const rs = xs.map(x=>x.c.realizedR).filter(r=>r!=null);
    const avgR = rs.length? (rs.reduce((a,b)=>a+b,0)/rs.length) : null;
    const pnl = xs.reduce((a,x)=>a+x.c.realized,0);
    return '<tr><td>'+esc(k)+'</td><td class="num">'+xs.length+'</td><td class="num">'+Math.round(wins/xs.length*100)+'%</td>'
      +'<td class="num '+(avgR!=null&&avgR>=0?'up':'dn')+'">'+(avgR!=null?(avgR>=0?'+':'')+avgR.toFixed(2)+'R':'—')+'</td>'
      +'<td class="num '+(pnl>=0?'up':'dn')+'" style="font-weight:700">'+(pnl>=0?'+':'')+Math.round(pnl)+'</td></tr>';
  }).join('');
  return '<div class="statsblock"><h3>按Setup类型分解</h3><table class="setupstats"><thead><tr><th>类型</th><th class="num">笔数</th><th class="num">胜率</th><th class="num">平均R</th><th class="num">盈亏$</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
}

// ===== v4.1: Setup A 台账命中率分析 =====
// 口径：命中率 = hit/(hit+partial+miss)，跟fetch_market_data.hit_stats一致；expired（未评定就过期）
// 单独显示不计入分母——它反映的是"跟踪断了"而不是"判断错了"，混进去会稀释真实命中率。
// 加权分 = (hit + 0.5*partial)/(hit+partial+miss)，把"部分兑现"算半分，比纯hit率更能反映实际收益。
function saScore(items){
  const h = items.filter(x=>x.verdict==='hit').length;
  const p = items.filter(x=>x.verdict==='partial').length;
  const m = items.filter(x=>x.verdict==='miss').length;
  const e = items.filter(x=>x.verdict==='expired').length;
  const n = items.filter(x=>!x.verdict).length;   // tracking中
  const dec = h+p+m;
  return {h,p,m,e,n,dec, rate: dec?h/dec:null, weighted: dec?(h+0.5*p)/dec:null};
}
// Setup字母的全名（2026-08-08 Vic："我一直忘记他们是什么"）。保留字母前缀方便跟报告里的写法对上，
// 后面接一个短到能塞进表格的中文描述——定义见CONTEXT.md「选股规则」。
// 全部用Vic自己的叫法（2026-08-08他口述：a=9ema pullback / b=tight / c=fakeout /
// d=pullback / e=spring / w=double wick）。注意两点：
// ①W他叫double wick，台账旧条目写的是"双底/三重底"，指同一个东西；
// ②B他明确"只有tight"——不追已经突破跑远的（见CONTEXT.md Setup B 2026-08-08修订）。
const SETUP_FULL = {
  A: "A·9ema pb",
  B: "B·tight",
  C: "C·fakeout",
  D: "D·pullback",
  E: "E·spring",
  W: "W·2 wick",
};
const setupLabel = k => SETUP_FULL[k] || k;

// setup字段是自由文本（"B+A+W三共振：tight(...)+回踩9EMA(...)"），从中抽出Setup字母标签。
// 一条可能同时含多个（B+A+W），各自都记一次——问的是"哪个方法命中高"，共振单要在每个成分里都算。
function saSetupTags(s){
  const txt = String(s||'');
  const tags = new Set();
  // 匹配 "Setup X" / 独立字母 / 组合 A+C+W 里的字母；只认 A-E 和 W(底部形态)
  (txt.match(/(?:Setup\s*)?\b([A-E]w?|W)\b/gi)||[]).forEach(m=>{
    const up = m.replace(/Setup\s*/i,'').trim().toUpperCase();
    if(/^(A|B|C|D|E|EW|W)$/.test(up)) tags.add(up==='EW'?'E':up);
  });
  // 中文描述兜底（有些条目只写了形态没写字母）
  if(/回踩9EMA/.test(txt)) tags.add('A');
  if(/tight/i.test(txt)) tags.add('B');
  if(/undercut/i.test(txt)) tags.add('C');
  if(/突破.*回踩|回踩.*突破/.test(txt)) tags.add('D');
  if(/shakeout|burst/i.test(txt)) tags.add('E');
  if(/双底|三重底|W底/.test(txt)) tags.add('W');
  return tags.size ? [...tags] : ['未标注'];
}
// sector也是自由文本（"XLF/IAK保险"、"网安CIBR + 软件IGV"），抽主板块代码
function saSectorTags(s){
  const txt = String(s||'');
  const tags = new Set();
  (txt.match(/\b(XL[KCYIFBEVPU]|XLRE|CIBR|IGV|IAK|KRE|XBI|IBB|IHI|PPH|SMH|XOP|DIA|XSW|NASA|ITA)\b/g)||[])
    .forEach(m=>tags.add(m));
  if(!tags.size){
    if(/保险/.test(txt)) tags.add('IAK');
    else if(/网安/.test(txt)) tags.add('CIBR');
    else if(/医疗|医药|医械/.test(txt)) tags.add('XLV');
    else if(/银行|券商|支付|资管|托管/.test(txt)) tags.add('XLF');
    else if(/能源|天然气/.test(txt)) tags.add('XLE');
    else if(/工业|国防/.test(txt)) tags.add('XLI');
  }
  return tags.size ? [...tags] : ['未标注'];
}
function saSourceTag(s){
  const m = String(s||'').match(/方法\s*\d+/);
  return m ? m[0].replace(/\s+/g,'') : (String(s||'').trim()==='' || /^[-—]$/.test(String(s||'').trim()) ? '未标注' : '其他');
}
// 总体结果分布：四根独立柱子（2026-08-08 Vic几轮反馈后定稿——先是堆叠条"格式坏了"，
// 试过饼图，最后回到柱状图）。分开画不会有堆叠条那种段与段之间的缝隙/圆角问题。
function resultBarChart(sc){
  const parts = [[sc.h,'命中','var(--soft-green)'],[sc.p,'部分','#dfe3e8'],
                 [sc.m,'失误','var(--soft-red)'],[sc.e,'过期未评定','#eef1f4']];
  const total = parts.reduce((a,p)=>a+p[0],0);
  if(!total) return '<p class="placeholder">还没有样本。</p>';
  const max = Math.max(...parts.map(p=>p[0]), 1);
  const H = 108;
  const bars = parts.map(([n,label,color])=>{
    const h = n ? Math.max(Math.round(n/max*H), 3) : 0;
    return '<div class="rbar" title="'+label+' '+n+'条（'+Math.round(n/total*100)+'%）">'
      +'<span class="rb-val">'+n+'</span>'
      +'<div class="rb-col" style="height:'+h+'px;background:'+color+'"></div>'
      +'<span class="rb-name">'+label+'</span>'
      +'<span class="rb-pct">'+Math.round(n/total*100)+'%</span></div>';
  }).join('');
  return '<div class="rbars">'+bars+'</div>';
}
function saBreakdownTable(groups, labelHead, labelFn){
  // groups: [[label, items], ...] —— 按已结算条数降序；labelFn可把字母换成全名
  const fmtLbl = labelFn || (k=>k);
  const rows = groups
    .map(([k,items])=>[k, items, saScore(items)])
    .filter(([k,items,sc])=>sc.dec>0)
    .sort((a,b)=>b[2].dec-a[2].dec);
  if(!rows.length) return '<p class="placeholder">还没有已结算样本。</p>';
  return '<table class="sa-break"><thead><tr><th>'+labelHead+'</th><th>已结算</th><th>命中</th><th>部分</th><th>失误</th><th>命中率</th><th>加权分</th></tr></thead><tbody>'
    +rows.map(([k,items,sc])=>{
      const rate = sc.rate==null?'—':Math.round(sc.rate*100)+'%';
      const w = sc.weighted==null?'—':Math.round(sc.weighted*100)+'%';
      const strong = sc.dec>=5;
      return '<tr><td class="lbl">'+esc(fmtLbl(k))+(strong?'':' <span class="muted" style="font-weight:400;font-size:11px">(样本少)</span>')+'</td>'
        +'<td>'+sc.dec+'</td>'
        +'<td style="color:var(--green)">'+(sc.h||'')+'</td>'
        +'<td class="muted">'+(sc.p||'')+'</td>'
        +'<td style="color:var(--red)">'+(sc.m||'')+'</td>'
        +'<td style="font-weight:800;color:'+(sc.rate>=0.5?'var(--green)':(sc.rate<0.25?'var(--red)':'var(--text)'))+'">'+rate+'</td>'
        +'<td>'+w+'</td></tr>';
    }).join('')+'</tbody></table>';
}
// ISO周起始日（周一），用于按周聚合看趋势
function weekStart(dstr){
  const d = new Date(dstr+'T00:00:00');
  const day = (d.getDay()+6)%7;           // 周一=0
  d.setDate(d.getDate()-day);
  return d.toISOString().slice(0,10);
}
function saTrendChart(items){
  const byWeek = {};
  items.forEach(x=>{ if(!x.date) return; (byWeek[weekStart(x.date)] = byWeek[weekStart(x.date)]||[]).push(x); });
  const weeks = Object.keys(byWeek).sort();
  if(weeks.length<2) return '<p class="placeholder">样本周数不足，还看不出趋势（至少要2周）。</p>';
  const bars = weeks.map(w=>{
    const sc = saScore(byWeek[w]);
    if(!sc.dec) return '<div class="tbar"><span class="tval muted">—</span><div class="tstack"></div><span class="tlabel">'+w.slice(5)+'</span></div>';
    const H = 96;
    const seg = (n,cls)=> n?'<div class="tseg '+cls+'" style="height:'+(n/sc.dec*H)+'px"></div>':'';
    const rate = Math.round(sc.rate*100);
    return '<div class="tbar" title="'+w+' 起这周：命中'+sc.h+'/部分'+sc.p+'/失误'+sc.m+'">'
      +'<span class="tval" style="color:'+(rate>=50?'var(--green)':(rate<25?'var(--red)':'var(--muted)'))+'">'+rate+'%</span>'
      +'<div class="tstack">'+seg(sc.h,'s-hit')+seg(sc.p,'s-part')+seg(sc.m,'s-miss')+'</div>'
      +'<span class="tlabel">'+w.slice(5)+'</span></div>';
  }).join('');
  // 前半段 vs 后半段，给一句结论
  const mid = Math.floor(weeks.length/2);
  const early = saScore(weeks.slice(0,mid).flatMap(w=>byWeek[w]));
  const late  = saScore(weeks.slice(mid).flatMap(w=>byWeek[w]));
  let verdict = '';
  if(early.dec>=3 && late.dec>=3 && early.rate!=null && late.rate!=null){
    const diff = (late.rate-early.rate)*100;
    const word = Math.abs(diff)<8 ? '基本持平' : (diff>0?'在改善':'在恶化');
    const cls = Math.abs(diff)<8 ? 'var(--muted)' : (diff>0?'var(--green)':'var(--red)');
    verdict = '<p class="note" style="margin:8px 0 0">前半段命中率 '+Math.round(early.rate*100)+'%（'+early.dec+'条）→ '
      +'后半段 '+Math.round(late.rate*100)+'%（'+late.dec+'条），<b style="color:'+cls+'">'+word+'</b>'
      +(Math.abs(diff)>=8?'（'+(diff>0?'+':'')+Math.round(diff)+'pct）':'')+'。</p>';
  } else {
    verdict = '<p class="note" style="margin:8px 0 0">样本还太少，前后对比暂不下结论。</p>';
  }
  return '<div class="trendbars">'+bars+'</div>'+verdict;
}
function groupBy(items, keyFn){
  const m = {};
  items.forEach(x=>{ const ks = keyFn(x); (Array.isArray(ks)?ks:[ks]).forEach(k=>{ (m[k]=m[k]||[]).push(x); }); });
  return Object.entries(m);
}

function render(){
  const open = state.trades.filter(t=>t.status==="open");
  const closed = state.trades.filter(t=>t.status==="closed").sort((a,b)=>(b.exit_date||"").localeCompare(a.exit_date||""));
  const done = closed.map(t=>({t,c:calc(t)})).filter(x=>!x.c.incomplete && x.c.realized!=null);
  const wins = done.filter(x=>x.c.realized>0).length;
  const rs = done.map(x=>x.c.realizedR).filter(r=>r!=null);
  // 平均持仓天数**排除日内**（2026-08-09 Vic：「平均持仓天数，应该去掉日内的」）——
  // 日内 holdDays 恒为 0，混进来会把均值系统性拉低，掩盖真实的非日内持仓节奏。
  // 日内笔数单列一格：它本身是要盯的指标（7/23复盘：0天持有胜率仅8%，是全部分桶最差）。
  const dt = closed.filter(t=>t.day_trade);
  const swing = closed.filter(t=>!t.day_trade);
  const hds = swing.map(holdDays).filter(x=>x!=null);
  const avgHold = hds.length ? (hds.reduce((a,b)=>a+b,0)/hds.length) : null;
  const kpi = [
    ["持仓中", open.length, ""], ["已平仓", closed.length, ""],
    ["胜率", done.length? Math.round(wins/done.length*100)+"%" : "—", ""],
    ["平均R", rs.length? ((rs.reduce((a,b)=>a+b,0)/rs.length>=0?"+":"")+(rs.reduce((a,b)=>a+b,0)/rs.length).toFixed(2)+"R") : "—", ""],
    ["平均持仓", avgHold!=null? avgHold.toFixed(1)+"天" : "—", "不含日内"],
    ["日内", dt.length+"笔", closed.length? Math.round(dt.length/closed.length*100)+"%" : ""],
  ].map(([k,v,sub])=>'<div class="kpi"><span>'+k+'</span><strong>'+v
      +(sub?'<em>'+sub+'</em>':'')+'</strong></div>').join('');

  const openView = open.filter(matchesSearch);
  const closedView = closed.filter(matchesSearch).filter(t=>matchesClosedFilters(t, calc(t)));

  const todoList = closed.filter(t=>todoMissing(t).length>0);
  const tabs = '<div class="tabs">'
    +'<span class="tabbtn'+(activeTab==="open"?" active":"")+'" onclick="setTab(\'open\')">持仓中 ('+open.length+')</span>'
    +'<span class="tabbtn'+(activeTab==="closed"?" active":"")+'" onclick="setTab(\'closed\')">已平仓 ('+closed.length+')</span>'
    +'<span class="tabbtn'+(activeTab==="todo"?" active":"")+'" onclick="setTab(\'todo\')">'+(todoList.length?'📝 ':'')+'待补齐 ('+todoList.length+')</span>'
    +'<span class="tabbtn'+(activeTab==="setupa"?" active":"")+'" onclick="setTab(\'setupa\')">A级复盘 ('+SETUP_HISTORY.length+')</span>'
    +'<span class="tabbtn'+(activeTab==="summaries"?" active":"")+'" onclick="setTab(\'summaries\')">每周复盘</span>'
    +'</div>';

  let body;
  if(activeTab==="closed"){
    const filterbar = '<div class="filterbar">'+CLOSED_FILTERS.map(([k,label])=>
      '<span class="fchip'+(closedFilters.has(k)?' active':'')+'" onclick="toggleFilter(\''+k+'\')">'+label+'</span>').join('')+'</div>';
    body = '<h2>已平仓</h2>'+filterbar+(closedView.map(tradeCard).join('')||'<p class="placeholder">没有匹配的交易。</p>')
      +'<div class="statsrow">'+monthlyChart(done)+setupBreakdown(done)+'</div>';
  } else if(activeTab==="todo"){
    // 点✏️就地展开完整表单，不跳去已平仓页——补完一笔还留在待补齐，可以接着补下一笔
    // （2026-08-07 Vic："每次补完一笔就跳回已平仓，又要再回去待补齐"）
    const editingTrade = editing ? state.trades.find(x=>x.id===editing) : null;
    body = '<h2>待补齐</h2>'
      +'<p class="placeholder" style="margin:0 0 10px">已平仓但还缺主观字段的交易，行内直接选，改完点顶栏「💾保存」。'
      +'日内不要求setup/逻辑/复盘，跟单不要求逻辑和执行质量。复盘只在平仓后第'+REVIEW_DUE_DAYS+'~'+REVIEW_DEAD_DAYS+'天之间催，过了'+REVIEW_DEAD_DAYS+'天就不再算欠账。实在不知道的就留空，别硬填。</p>'
      +(editingTrade ? tradeForm(editingTrade) : '')
      // 正在编辑的那笔从表格里摘掉——否则同一笔会有两套输入控件（表单里的和行内的），
      // commitEdit和updateTodoField会互相覆盖
      +(()=>{ const rows = todoList.filter(t=>t.id!==editing);
        return rows.length
          ? '<table class="todo-table"><thead><tr><th>Ticker</th><th>盈亏$</th><th>Setup</th><th>买入逻辑</th><th>执行质量</th><th>复盘</th><th>还缺</th><th></th></tr></thead><tbody>'
            +rows.map(todoRow).join('')+'</tbody></table>'
          : (editingTrade ? '' : '<p class="todo-done">✓ 全部补齐了，没有欠账。</p>'); })();
  } else if(activeTab==="setupa"){
    const V={hit:["命中","v-hit"],partial:["部分","v-part"],miss:["失误","v-miss"],
             expired:["过期未评定","v-exp"]};
    const q=searchQuery.trim().toLowerCase();
    const list=SETUP_HISTORY.filter(x=>!q||(x.ticker+" "+(x.sector||"")+" "+(x.setup||"")).toLowerCase().includes(q));
    const all = SETUP_HISTORY;
    const sc = saScore(all);
    const kpis = [
      ['已结算', sc.dec, ''],
      ['命中率', sc.rate==null?'—':Math.round(sc.rate*100)+'%', 'hit'],
      ['加权分', sc.weighted==null?'—':Math.round(sc.weighted*100)+'%', ''],
      ['命中', sc.h, 'hit'], ['部分', sc.p, ''], ['失误', sc.m, 'miss'],
      ['过期未评定', sc.e, ''],
      // 注意：这份数据只含已结案条目（report_helpers.setup_track_history 过滤 status==closed），
      // 所以不显示"跟踪中"——那个数永远是0，摆上去反而误导。
    ].map(([k,v,cls])=>'<div class="sa-kpi'+(cls?' '+cls:'')+'"><span>'+k+'</span><strong>'+v+'</strong></div>').join('');
    body='<h2>A级复盘</h2>'
      +'<div class="sa-kpis">'+kpis+'</div>'
      +'<div class="statsblock"><h3>总体结果分布（含过期）</h3>'+resultBarChart(sc)+'</div>'
      +'<div class="statsblock"><h3>命中率随时间变化（按周）</h3>'+saTrendChart(all)+'</div>'
      +'<div class="statsrow">'
        +'<div class="statsblock"><h3>按 Setup 类型（共振单在每个成分里各记一次）</h3>'
          +saBreakdownTable(groupBy(all, x=>saSetupTags(x.setup)), 'Setup', setupLabel)+'</div>'
        +'<div class="statsblock"><h3>按扫描来源方法</h3>'
          +saBreakdownTable(groupBy(all, x=>saSourceTag(x.source)), '来源')+'</div>'
      +'</div>'
      +'<div class="statsblock"><h3>按板块</h3>'
        +saBreakdownTable(groupBy(all, x=>saSectorTags(x.sector)), '板块')+'</div>'
      +'<h3 style="margin:18px 0 6px">全部条目'+(q?'（搜索「'+esc(q)+'」）':'')+'</h3>'
      +(list.length?('<table class="sa-table"><thead><tr><th>信号日</th><th>TICKER</th><th>板块</th>'
      +'<th>入场</th><th>失效</th><th>结果</th><th>来源</th></tr></thead><tbody>'
      +list.map(x=>{const v=V[x.verdict]||[x.verdict||"跟踪中",""];
        return '<tr><td>'+x.date+'</td><td><b>'+x.ticker+'</b></td><td>'+(x.sector||"-")+'</td>'
          +'<td>'+(x.entry||"-")+'</td><td>'+(x.invalid||"-")+'</td>'
          +'<td><span class="vbadge '+v[1]+'">'+v[0]+'</span></td><td>'+(x.source||"-")+'</td></tr>';
      }).join('')+'</tbody></table>'):'<p class="placeholder">暂无归档。</p>');
  } else if(activeTab==="summaries"){
    const rows = dailyLineRows();
    body = '<h2>每周复盘</h2>'
      +rows.map(({date,s,label})=>
        '<div class="wkcard"><div class="wkhead">'+esc(label)+'</div>'
        +renderWeekly(s && s.summary_kind==='weekly' ? s.summary : null)
        +'<input class="dl-input wk-input" value="'+esc((s&&s.vic_summary)||"")+'" placeholder="加一句你自己的…"'
        +' onchange="setDailyLine(\''+date+'\',this.value)"></div>').join('');
  } else {
    body = '<h2>持仓中</h2>'+(openView.map(tradeCard).join('')||'<p class="placeholder">'+(searchQuery?'没有匹配的交易。':'当前无持仓。')+'</p>');
  }

  $("#app").innerHTML = '<div class="kpis">'+kpi+'</div>' + tabs + body;
  const sb = $("#searchbox"); if(sb && sb.value!==searchQuery) sb.value = searchQuery;
  paintEmpty();
}

// v4改成白名单制（2026-08-07 Vic："有时候不知道输入什么就大概填一下"——被逼填出来的假数据比空白更糟）。
// 只有真正必填的才标红：ticker、每笔leg的股数/价格、初始止损价。其他一律允许空着。
const REQUIRED_RE = /^(f_ticker|lg_q_\d+|lg_p_\d+|st_s_0)$/;
// 日内交易免填初始止损（2026-08-09 Vic：「日内不要记录止损了，没用的吧」）——
// 日内是当天进出，止损位不构成过夜风险边界，R 也算不出有意义的值；
// 填了只是为了让红框消失的假数据。**非日内仍然必填**，那是真正的风控。
const REQUIRED_RE_DT = /^(f_ticker|lg_q_\d+|lg_p_\d+)$/;
function paintEmpty(){
  // 日内标记在 state 里（分段按钮 toggleDT），不是 DOM checkbox——从正在编辑的那笔读
  const et = editing ? state.trades.find(x=>x.id===editing) : null;
  const re = (et && et.day_trade) ? REQUIRED_RE_DT : REQUIRED_RE;
  document.querySelectorAll('.editform').forEach(form=>{
    form.querySelectorAll('input:not([type=checkbox]), textarea, select').forEach(el=>{
      if(!el.id || !re.test(el.id)){ el.classList.remove('empty-field'); return; }
      el.classList.toggle('empty-field', !String(el.value||'').trim() || el.value==='0');
    });
  });
}
document.addEventListener('input', e=>{ if(e.target.closest('.editform')) paintEmpty(); });
document.addEventListener('change', e=>{ if(e.target.closest('.editform')) paintEmpty(); });

// ---------- 保存：File System Access API + IndexedDB记住文件句柄 ----------
const idb = { db:null,
  async open(){ if(this.db) return this.db;
    this.db = await new Promise((res,rej)=>{ const r = indexedDB.open("tradebook",1);
      r.onupgradeneeded = ()=>r.result.createObjectStore("kv");
      r.onsuccess = ()=>res(r.result); r.onerror = ()=>rej(r.error); });
    return this.db; },
  async get(k){ const db = await this.open();
    return new Promise(res=>{ const tx = db.transaction("kv").objectStore("kv").get(k);
      tx.onsuccess = ()=>res(tx.result); tx.onerror = ()=>res(null); }); },
  async set(k,v){ const db = await this.open();
    return new Promise(res=>{ const tx = db.transaction("kv","readwrite").objectStore("kv").put(v,k);
      tx.onsuccess = ()=>res(); tx.onerror = ()=>res(); }); }
};
async function getHandle(){
  // 2026-07-09事故修复：Vic在选择器里选到了 tradebook.html（网页本体），JSON直接覆盖了应用页面。
  // 现在只接受 .json 文件；选错就提示重选，永远不可能再写坏网页。
  let h = await idb.get("fh");
  if(h && /\.json$/i.test(h.name)){
    if(await h.queryPermission({mode:"readwrite"})==="granted" || await h.requestPermission({mode:"readwrite"})==="granted") return h;
  }
  while(true){
    const [nh] = await window.showOpenFilePicker({
      types:[{description:"tradebook.json 数据文件",accept:{"application/json":[".json"]}}],
      excludeAcceptAllOption:true});
    if(/\.json$/i.test(nh.name)){ await idb.set("fh", nh); return nh; }
    alert("选错文件了：请选 data 文件夹里的 tradebook.json（数据文件），不是网页 tradebook.html！");
  }
}
// baselineSnapshot：这个页面"确认见过"的每笔交易的完整快照（id -> JSON文本），每次成功读到磁盘最新内容
// （初始快照/loadFresh/reauthAndReload/保存成功后）都会刷新。保存前重新读一次磁盘，跟这份快照三方比对：
//   - 磁盘有、baseline没有 → 这个页面从没见过的新交易，保存会删掉它
//   - 磁盘内容 != baseline内容，但页面当前内容 == baseline（页面没动过这笔）→ 别处改过/加过内容
//     （比如平仓、补止损轨迹、填卖后追踪），这个页面完全不知情，保存会把那些内容退回旧版本——
//     2026-07-30事故就是这样：SMH/SPCX/WAT/CIFR/VRTX/HAE 已经在磁盘上被关闭并写好复盘，
//     但这个页面还停留在它们"刚建仓"的旧版本，保存直接把磁盘上更完整的记录覆盖回了旧版本
//   - 磁盘内容 != baseline 且 页面内容 != baseline（两边都改了）→ 真正的冲突，谁都不能替谁做主
// 三种情况都必须挡下来，不能只挡第一种（那只是最容易看见的冰山一角）。
let baselineSnapshot = new Map((state.trades||[]).map(t=>[t.id, JSON.stringify(t)]));

async function saveFile(){
  if(document.getElementById('stalebanner') && !confirm(
    "当前页面数据可能不是最新的（上次打开时文件读写权限已过期，没能确认读到的是最新版）。\n"+
    "现在保存有覆盖掉你在别处/别的时间保存过的修改的风险。\n\n"+
    "建议先点上面的「刷新最新数据」，确认无误后再保存。\n\n仍要现在保存吗？")) return;
  try{
    const h = await getHandle();
    // 2026-07-30事故修复第二版：光比对id集合不够——上面事故的6笔交易的id这个页面其实都"见过"
    // （baseline里有），问题是磁盘上的内容比这个页面手里的更新（已经平仓/填了复盘），页面却不知道，
    // 保存时用旧内容覆盖回去了。改成对每一笔的完整内容做三方比对（磁盘 vs baseline vs 页面当前），
    // 不只是比"有没有这个id"。
    try{
      const preFile = await h.getFile();
      const preData = JSON.parse(await preFile.text());
      const curById = new Map(state.trades.map(t=>[t.id, JSON.stringify(t)]));
      const newOnDisk = [], externalUpdate = [], conflict = [];
      for(const t of (preData.trades||[])){
        const diskJson = JSON.stringify(t);
        const baseJson = baselineSnapshot.get(t.id);
        const curJson = curById.get(t.id);
        if(diskJson === curJson) continue;               // 页面已经跟磁盘这笔一致，没风险
        if(baseJson === undefined){ if(curJson===undefined) newOnDisk.push(t); }
        else if(diskJson !== baseJson){
          if(curJson === baseJson) externalUpdate.push(t);          // 页面没动过，磁盘却变了：会被静默退回旧版本
          else if(curJson !== undefined) conflict.push(t);          // 两边都动过：真冲突
        }
      }
      const atRisk = [...newOnDisk, ...externalUpdate, ...conflict];
      if(atRisk.length){
        const label = t => (t.ticker||'(空)')+'/'+(t.entry_date||'?');
        const parts = [];
        if(newOnDisk.length) parts.push("这个页面从没见过的新交易："+newOnDisk.map(label).join('、'));
        if(externalUpdate.length) parts.push("磁盘上内容更新但这个页面还是旧版本（保存会退回旧版本）："+externalUpdate.map(label).join('、'));
        if(conflict.length) parts.push("磁盘和这个页面都改过、内容对不上（保存会丢掉磁盘那边的改动）："+conflict.map(label).join('、'));
        if(!confirm(
          "⚠ 磁盘上有"+atRisk.length+"笔交易跟这个页面手里的不一致：\n"+parts.join("\n")+
          "\n\n继续保存会用这个页面手里的内容覆盖磁盘，上面这些改动会丢。\n\n"+
          "建议取消，先点「🔄刷新最新数据」确认合并后再保存。\n\n仍要现在保存（丢弃这些改动）吗？")) { showStaleBanner(); return; }
      }
    }catch(e){ /* 磁盘读取/解析失败就跳过这层比对，不阻塞正常保存 */ }
    const w = await h.createWritable();
    await w.write(JSON.stringify(state, null, 2));
    await w.close();
    baselineSnapshot = new Map(state.trades.map(t=>[t.id, JSON.stringify(t)]));
    dirty = false;
    $("#savestate").innerHTML = '<span class="saved-ok">✓ 已保存 '+new Date().toLocaleTimeString()+'</span>';
    const banner = document.getElementById('stalebanner'); if(banner) banner.remove();
  }catch(e){
    if(e.name!=="AbortError") alert("保存失败："+e.message+"\n可用「导出JSON备份」手动替换 data/tradebook.json");
  }
}
function exportJson(){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:"application/json"}));
  a.download = "tradebook.json"; a.click();
}
window.addEventListener("beforeunload", e=>{ if(dirty){ e.preventDefault(); e.returnValue=""; } });

// 2026-07-09修复：网页里嵌的state是build_tradebook.py上次跑的时候的快照，保存只写了data/tradebook.json，
// 从没让页面重新打开时去读那个文件——所以每次关掉重开都会倒退回旧快照，看起来像"保存了又没了"（其实数据在json里没丢）。
// 现在页面一打开就静默尝试读已授权的文件句柄（queryPermission不会弹窗），读到就用它覆盖嵌入的旧数据，
// 这样data/tradebook.json才是真正唯一的数据源，跟页脚说的一致。
// 2026-07-28修复第二版：上面那个修复本身有洞——浏览器的文件读写权限句柄不总是能跨会话保留
// （比如隔天重开、换个浏览器窗口），queryPermission返回非granted时上面的代码是"悄悄放弃、什么都不提示"，
// 页面照样显示嵌入的旧快照，跟真正读到最新数据长得一模一样，用户根本分不出这是"最新的"还是"旧快照"——
// Vic原话："我昨天改了两次，今天打开，修改的又都没了"，查data/tradebook.json发现他的修改其实都在，
// 只是页面没读到，属于这个洞。修复：查不到最新数据时不再默默无视，显眼地提示，并给一个按钮让用户主动点击
// 重新授权刷新（必须由用户手势触发requestPermission，不能自动弹窗）；点💾保存前如果还处于这个"未确认最新"
// 状态，先弹确认框拦一下，防止拿旧快照当底稿保存把别的修改覆盖掉。
function showStaleBanner(){
  if(document.getElementById('stalebanner')) return;
  const b = document.createElement('div');
  b.id = 'stalebanner';
  b.style = 'position:sticky;top:0;z-index:49;background:var(--amber-bg);border:1px solid #e8c3b8;border-radius:12px;'
    +'padding:10px 14px;margin-bottom:12px;font-size:14.5px;font-weight:700;color:#7a4a1c;display:flex;'
    +'align-items:center;gap:10px;flex-wrap:wrap';
  b.innerHTML = '⚠ 当前显示的可能不是最新数据（文件读写权限需要重新确认，不确认就不会自动刷新）'
    +'<button class="btn small primary" onclick="reauthAndReload()">🔄 点击刷新最新数据</button>';
  const wrap = document.querySelector('.wrap');
  wrap.insertBefore(b, document.querySelector('.topbar'));
}
async function reauthAndReload(){
  try{
    const h = await getHandle();  // 由点击触发，可以正常requestPermission弹授权框
    const file = await h.getFile();
    const fresh = JSON.parse(await file.text());
    if(fresh && Array.isArray(fresh.trades)){
      state = fresh; baselineSnapshot = new Map(fresh.trades.map(t=>[t.id, JSON.stringify(t)]));
      editing = null; render();
      const b = document.getElementById('stalebanner'); if(b) b.remove();
    } else {
      alert("读到的文件内容不像tradebook.json（没有trades数组），没有覆盖当前页面。");
    }
  }catch(e){
    if(e.name!=="AbortError") alert("刷新失败："+e.message);
  }
}
async function loadFresh(){
  try{
    const h = await idb.get("fh");
    if(!h || !/\.json$/i.test(h.name)) return;  // 从没存过/句柄丢了：用嵌入快照兜底，不算"过期"，不提示
    if(await h.queryPermission({mode:"readwrite"}) !== "granted"){ showStaleBanner(); return; }
    const file = await h.getFile();
    const fresh = JSON.parse(await file.text());
    if(fresh && Array.isArray(fresh.trades)){ state = fresh; baselineSnapshot = new Map(fresh.trades.map(t=>[t.id, JSON.stringify(t)])); render(); }
  }catch(e){ showStaleBanner(); }
}

// 2026-07-30新增：之前drift检查只在"点保存那一刻"才做，意味着这个标签页可能已经在旧数据上面
// 敲了很久（甚至录了很多笔新交易）才发现磁盘早就不一样了——保存时的检查能拦住数据被覆盖，但拦不住
// "白敲了一小时"这种体验损耗。加一个安静的背景检查：切回这个标签页时、以及每2分钟一次，
// 悄悄查一下磁盘内容是否跟baseline对不上（只用queryPermission不弹权限框，不主动requestPermission，
// 不打断正在编辑的表单），发现不对就显示banner——不阻塞任何操作，只是尽早提醒，
// 比等到点保存才发现要好得多。
async function checkDriftSilently(){
  try{
    const h = await idb.get("fh");
    if(!h || !/\.json$/i.test(h.name)) return;
    if(await h.queryPermission({mode:"readwrite"}) !== "granted") return;
    const file = await h.getFile();
    const diskData = JSON.parse(await file.text());
    const curById = new Map(state.trades.map(t=>[t.id, JSON.stringify(t)]));
    for(const t of (diskData.trades||[])){
      const diskJson = JSON.stringify(t);
      const baseJson = baselineSnapshot.get(t.id);
      const curJson = curById.get(t.id);
      if(diskJson === curJson) continue;
      if(baseJson === undefined && curJson === undefined){ showStaleBanner(); return; }
      if(baseJson !== undefined && diskJson !== baseJson && curJson === baseJson){ showStaleBanner(); return; }
    }
  }catch(e){ /* 静默失败，不打扰；真正兜底的检查在保存时那一道 */ }
}
document.addEventListener('visibilitychange', ()=>{ if(document.visibilityState==='visible') checkDriftSilently(); });
setInterval(checkDriftSilently, 120000);

render();
loadFresh();
</script>
</body>
</html>
"""


def build():
    store = migrate(json.loads(TB_PATH.read_text(encoding="utf-8")))
    # 2026-08-08：改成导入**周报**总结（不再是每日盘后全文——Vic说日总结那页他不看）。
    import_summaries(store)
    TB_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    data_js = json.dumps(store, ensure_ascii=False).replace("</", "<\\/")
    # Setup A历史（2026-07-28）：来源是 data/setup_track.json，构建时独立注入，
    # 不并进 store，也就绝不会写进 Vic 自己维护的 data/tradebook.json
    try:
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import report_helpers as _H
        _latest = sorted((pathlib.Path(__file__).resolve().parent.parent
                          / "data" / "cache").glob("market_*.json"))[-1]
        _hist = _H.setup_track_history(_H.load_cache(_latest.stem.replace("market_", "")))
    except Exception as _e:
        print(f"(Setup A历史读取失败，标签页将为空: {_e})")
        _hist = []
    hist_js = json.dumps(_hist, ensure_ascii=False).replace("</", "<\\/")
    html_out = (APP_TEMPLATE
                .replace("__CSS__", CSS_PATH.read_text(encoding="utf-8"))
                .replace("__DATA__", data_js)
                .replace("__SETUP_HISTORY__", hist_js))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_out, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(f"Wrote {build()}")
