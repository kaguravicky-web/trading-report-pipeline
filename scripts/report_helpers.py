#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前/盘后报告的"机械骨架"生成器（2026-07-12建，省token用）。

设计原则：这里只放纯数字/纯规则的转换——cache里已经算好的东西原样搬进表格行，
不含任何需要新闻/催化剂/综合判断的内容。每天写报告时 import 这个模块，
把返回的骨架当基础，只手写"为什么"那一栏（reason/judgment/note列）和
需要综合判断的模块（信号灯纪律、情景分析、核心结论、setup分级理由）。

如果发现自己在这个文件里写"为什么"，说明放错地方了——挪回当天的assemble脚本。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_cache(date_str: str) -> dict:
    """date_str: 'YYYYMMDD'"""
    return json.load(open(ROOT / "data" / "cache" / f"market_{date_str}.json", encoding="utf-8"))


def load_premarket_snap(date_str: str) -> dict:
    p = ROOT / "data" / "cache" / f"premarket_{date_str}.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else {}


def load_setups(date_str: str) -> dict:
    p = ROOT / "data" / "cache" / f"setups_{date_str}.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else {"hits": {}}


def tri3(cache: dict, ticker: str) -> str:
    """20/50/200MA的标注三元组，格式"20▲ 50▲ 200▼"（顺序固定，空格分隔）。
    2026-07-21改版对标老师报告的Above MA样式——render_report.py的build_ma_cell()会把这个
    文本格式解析成带period标签的独立小chip（<span class="ma">...</span>），不再是原来纯▲▼
    三字符文本（旧格式"▲▲▼"）。这个函数只管产出可解析的纯文本，不掺HTML，HTML组装留给渲染层。"""
    m = cache["metrics"].get(ticker, {})

    def a(period, v):
        arrow = "▲" if (v is not None and v >= 0) else ("▼" if v is not None else "-")
        return f"{period}{arrow}"

    return " ".join([a(20, m.get("dist_ma20_pct")), a(50, m.get("dist_ma50_pct")), a(200, m.get("dist_ma200_pct"))])


def badge(kind: str, text: str) -> str:
    """行内彩色标签（Beat/Miss/Mixed类判断），对标老师报告的<span class='badge green'>Beat</span>
    样式（2026-07-21新增）。kind取green/red/amber/blue（对应templates/report.css既有的.badge颜色）。
    返回的字符串已经是完整HTML，调用方要把所在列加进表格的raw_cols（否则会被build_table二次转义）。"""
    from html import escape
    return f'<span class="badge {kind}">{escape(str(text))}</span>'


def fpct(v, na="-"):
    return na if v is None else ("%+.2f%%" % v)


def rs_week(cache: dict, ticker: str):
    """RS = 对QQQ的1周(5日)超额收益（CONTEXT.md定义）。2026-07-15 Vic最终定案：全报告RS统一只看
    1周，不再显示1日/5日双值（当天先试了双值格式，Vic当天又纠正"只看一周的，说过了"）。"""
    M = cache["metrics"]
    m, q = M.get(ticker) or {}, M.get("QQQ") or {}
    a, b = m.get("d5_pct"), q.get("d5_pct")
    return None if (a is None or b is None) else round(a - b, 2)


def rs_num(v) -> str:
    return "-" if v is None else ("%+.1f" % v)


def sector_rs_rows(cache: dict, tickers: list, pm_cache: dict = None) -> list:
    """板块RS表骨架：[ticker, T-1%, 5日%, 1月%, ""(驱动), RS(1周)]——**六列**。
    驱动列留空当天手写。已按T-1%降序。

    🔴 2026-08-12：「盘前」列删除（Vic：「我觉得盘前数字没什么用…关于盘前的全部删了吧」）。
    `pm_cache` 参数保留但被忽略，只为旧调用点不报 TypeError。"""
    M = cache["metrics"]
    data = []
    for tk in tickers:
        m = M.get(tk) or {}
        data.append((tk, m.get("t1_pct"), m.get("d5_pct"), m.get("d21_pct")))
    data.sort(key=lambda x: (x[1] is None, -(x[1] or -999)))
    rows = []
    for tk, t1, d5, d21 in data:
        rows.append([tk, fpct(t1), fpct(d5), fpct(d21), "", rs_num(rs_week(cache, tk))])
    return rows


# 板块家族（2026-07-27新增，Vic："我想xle不好，xop oih会联动吧"）。
# 每个family的第一只是"锚"（最广的那只板块ETF）。实测60日日收益相关系数：
# XLE↔XOP 0.936、XLE↔OIH 0.643、XLE↔USO 0.759；对照组 XLE↔XLV 仅0.083、XLE↔PPH 0.069。
# 即：XOP几乎就是加杠杆的XLE，把它们同时放进榜单等于同一个赌注占三个名额。
SECTOR_FAMILY = {
    "energy": ["XLE", "XOP", "OIH", "USO"],
    "semis": ["SMH", "DRAM", "KOID", "EUV"],
    "china": ["FXI", "KWEB", "ASHR"],
    "crypto": ["IBIT", "ETHB", "WGMI"],
    "metals": ["GLD", "SLV", "COPX", "REMX", "LIT"],
    "health": ["XLV", "PPH", "IHI", "XBI"],
    "financials": ["XLF", "KRE", "IAK"],
    "industrials": ["XLI", "PAVE", "AIRR", "ITA", "NASA", "JETS"],
    "tech": ["XLK", "IGV", "CIBR", "AIQ", "QTUM", "ARKK", "MAGS"],
}
_TICKER_FAMILY = {t: f for f, ts in SECTOR_FAMILY.items() for t in ts}
_FAMILY_ANCHOR = {f: ts[0] for f, ts in SECTOR_FAMILY.items()}


def _corr(cache: dict, a: str, b: str) -> float:
    """从cache['family_corr']取两只的实测相关系数；缺失(未同族/未计算)按0处理=当作不相关。"""
    fc = cache.get("family_corr") or {}
    return fc.get("%s|%s" % (a, b), fc.get("%s|%s" % (b, a), 0.0))


def unilateral_rows(cache: dict, top_n: int = 5, stages=(1, 2), family_dedupe: bool = True,
                    min_score: int = 2):
    """单边板块榜：[排名, TICKER, 得分, Weinstein, 通过项, 5日%, 1月%, RS(1周), 距50MA, 延伸档位]。

    2026-07-27 Vic两项要求：①只放5个板块（原8个）②加Weinstein筛选，确认在Stage 1/2。
    Stage 3(派发)/Stage 4(下降)的板块即使4项结构分打满也不进榜——结构分只看最近10天，
    Weinstein看的是30周均线的方向，两者冲突时以后者为准（"单边"本来就该是中期趋势概念）。
    返回(rows, row_highlights)：距50MA≥5×ATR的行标红。
    """
    ext_label = {"extreme": "EXTREME（回踩类减半仓）", "high": "HIGH（只做回踩类）", "mild": "mild", "ok": "ok"}
    ST = {1: "Stage 1 筑底", 2: "Stage 2 上升", 3: "Stage 3 派发", 4: "Stage 4 下降"}
    M = cache.get("metrics", {})
    rows, hl = [], []
    used_families = set()
    for it in cache.get("unilateral_scan", []):
        tk = it["ticker"]
        st = (M.get(tk) or {}).get("weinstein_stage")
        if stages and st not in stages:
            continue
        # 结构分门槛：单边板块榜的前提就是"结构成立"，0-1分的不该占名额
        if it["score"] < min_score:
            continue
        if family_dedupe:
            fam = _TICKER_FAMILY.get(tk)
            if fam:
                # 判据是**实测相关系数**，不是family名义（2026-07-27实测：同一family内
                # XOP↔XLE 0.94 但 OIH↔XLE 只有0.64；PPH↔XLV 0.91 但 XBI↔XLV 只有0.32。
                # 按family一刀切会误杀真正独立的子板块）。
                # ①与已处于Stage 3/4的板块母ETF高度同步(ρ≥0.85) → 同一个赌注，母板块在派发
                #   就说明这条线的钱在撤（XOP被XLE带走正是这种情况）
                anchor = _FAMILY_ANCHOR[fam]
                if tk != anchor and (M.get(anchor) or {}).get("weinstein_stage") in (3, 4) \
                        and _corr(cache, tk, anchor) >= 0.85:
                    continue
                # ②与已入榜的任一只高度同步 → 不重复占名额
                if any(_corr(cache, tk, sel) >= 0.85 for sel in used_families):
                    continue
                used_families.add(tk)
        rows.append([str(len(rows) + 1), it["ticker"], "%d/4" % it["score"], ST.get(st, "-"),
                     "·".join(it.get("passed", [])) or "-",
                     fpct(it.get("d5_pct")), fpct(it.get("d21_pct")),
                     rs_num(rs_week(cache, it["ticker"])),
                     ("%.2f×ATR" % it["dist_ma50_atr"]) if it.get("dist_ma50_atr") is not None else "-",
                     ext_label.get(it.get("extension", "ok"), "ok")])
        hl.append("warn" if (it.get("dist_ma50_atr") is not None and it["dist_ma50_atr"] >= 5) else "")
        if len(rows) >= top_n:
            break
    return rows, hl




# 2026-07-28 Vic两条合并："B·指数顺序是…E·指数基准也是这几个指数、这个顺序，盘后也应该是"
# +"spy全部报告改voo吧，不要两个都写"。
# 此前三处各排各的（盘前B: SPY QQQ QQQE RSP DIA IWM VOO SMH / 盘前E: IWM DIA VOO QQQ /
# 盘后: 按涨跌排序），且SPY和VOO并列重复。定成**唯一常量**，所有指数表引用它，不各自维护顺序。
INDEX_ORDER = ["VOO", "QQQ", "DIA", "IWM", "SMH", "RSP", "QQQE"]
ATR_EXT_INDICES = INDEX_ORDER


def order_index_rows(rows, key=lambda r: r[0]):
    """把任意指数行按INDEX_ORDER重排；不在名单里的排最后、保持原相对顺序。"""
    idx = {t: i for i, t in enumerate(INDEX_ORDER)}
    return sorted(rows, key=lambda r: idx.get(str(key(r)).split()[0], 999))


def atr_extension_trend(dist):
    """距50MA(ATR)趋势分档（2026-07-27新增，借鉴Vic老师报告格式，见CONTEXT.md/render_report.py同名注释）。
    阈值用老师报告的8个真实样本反推校准：VOO-0.92/SPY-0.87/QQQ-2.59/QQQE-2.08→下降；
    RSP+1.77→相对强；DIA+0.82→横盘偏强；IWM-0.01→临界；SMH-1.53→下降，8/8命中。"""
    if dist is None:
        return None
    if abs(dist) < 0.3:
        return "临界"
    if dist <= -0.3:
        return "下降"
    return "相对强" if dist >= 1.2 else "横盘偏强"


def atr_extension_rows(cache: dict, tickers: list = None) -> list:
    """指数50MA ATR延伸表数据（2026-07-27新增）。返回list[dict]，交给
    render_report.build_atr_extension_table()渲染。judgment是机械生成的默认文案，
    组装报告时可在上层覆盖更具体的判断（同sector_rs_note等表的"表+note覆盖"模式）。"""
    tickers = tickers or ATR_EXT_INDICES
    m = cache.get("metrics", {})
    rows = []
    for t in tickers:
        r = m.get(t, {})
        dist = r.get("dist_ma50_atr")
        if dist is None:
            continue
        trend = atr_extension_trend(dist)
        # 2026-07-27 Vic："判断里面为什么需要说 低于50MA 0.75ATR 这种废话，前面都有了"——
        # 判断列只写这个数字的**含义**，不复述已经在「距50MA ATR」列里的数值。
        if trend == "下降":
            judge = "趋势未修复，但未过度延伸" if abs(dist) < 1.5 else "压力持续加深"
        elif trend == "临界":
            judge = "方向未定，下一交易日确认"
        elif trend == "横盘偏强":
            judge = "守稳，未转强"
        else:
            judge = "相对强势格局"
        rows.append({
            "ticker": t, "close": r2(r.get("close")), "ma50": r2(r.get("ma50")),
            "atr14": r2(r.get("atr14")), "dist_ma50_atr": dist,
            "trend": trend, "judgment": judge,
        })
    return rows


def r2(v):
    """全报告统一2位小数（2026-07-27 Vic："全报告2位小数，除非是fx那些特殊的"）。
    汇率/利率这类需要更多位的，调用方自己格式化，不要走这个函数。"""
    if v is None:
        return "-"
    try:
        return "%.2f" % float(v)
    except (TypeError, ValueError):
        return str(v)


def gate_etf_rows(cache: dict, tickers: list) -> list:
    """大盘ETF技术总表骨架：[ETF, 收盘, 日变化, 进攻线, 谨慎线, 降级线, 50MA, 距50MA, ""]——
    闸门线只对gate_reference里有的ticker(通常SPY/QQQ/IWM)填实际值，其余三列"-"。
    最后一列(判断)留空，当天手写。"""
    M, G = cache["metrics"], cache.get("gate_reference", {})
    rows = []
    for tk in tickers:
        m = M.get(tk) or {}
        g = G.get(tk)
        if g:
            row = [tk, str(m.get("close", "-")), fpct(m.get("t1_pct")),
                   str(g.get("ma20_plus_1atr", "-")), str(g.get("ma20", "-")),
                   str(g.get("ma20_minus_1atr", "-")), str(g.get("ma50", "-")),
                   ("%.1f×ATR" % ((m["close"] - g["ma50"]) / g["atr14"])) if (m.get("close") and g.get("atr14")) else "-",
                   ""]
        else:
            row = [tk, str(m.get("close", "-")), fpct(m.get("t1_pct")), "-", "-", "-",
                   str(m.get("ma50", "-")),
                   ("%.1f×ATR" % m["dist_ma50_atr"]) if m.get("dist_ma50_atr") is not None else "-", ""]
        rows.append(row)
    return rows


def fmt_shares(v) -> str:
    """成交量友好格式：128.4万 / 3.2万 / 850。"""
    if v is None:
        return "-"
    v = float(v)
    return ("%.1f万" % (v / 10000)) if v >= 10000 else ("%d" % v)


def pm_volume_cell(pm_cache: dict, ticker: str):
    """Premarket Movers用（2026-07-15 Vic要求区分'大量涨'还是'低量'）：
    返回(盘前量字符串, 量能标签)。标签只在snap_premarket.py算出了vol_ratio_pm（该标的触发MOVER门槛）
    时才判定：量比≥20%（盘前已成交量占20日均量两成以上）→'放量'；<5%→'低量·谨慎'（小单容易打出虚高%）；
    中间不标注。未计算量比（没触发门槛/数据不足）时标签为'-'。"""
    v = pm_cache.get(ticker) or {}
    vol_s = fmt_shares(v.get("pm_vol"))
    ratio = v.get("vol_ratio_pm")
    if ratio is None:
        return vol_s, "-"
    # 2026-08-06 Vic：「量能下面 低量·谨慎 改成 高 低，因为已经有红绿了」——
    # 颜色已经承载了严重度，文字只需要一个字表明方向
    if ratio >= 0.20:
        return vol_s, "高"
    if ratio < 0.05:
        return vol_s, "低"
    return vol_s, "-"


def position_pm_alert(pm_cache: dict, ticker: str) -> str:
    """持仓票盘前异动标注（2026-07-15 SYK教训：盘前量很大但价没到7%门槛，完全静默，当天暴跌）。
    snap_premarket.py已按 |盘前%|≥3 或 量比≥10% 打好pos_alert标；这里把触发内容拼成
    "盘前异动 -3.2%·量比14%" 样式给持仓监控表用，未触发返回空串。

    **2026-08-07 改「警报」为「异动」**：Vic 指出 MRVL 盘前 **+3.73%** 那行被染成红底，
    「红色似乎不对」。原实现对任何方向的大幅波动都叫"警报"、都标红，
    **而对持仓来说上涨和下跌是相反的事**。措辞与配色都改成中性/按方向，见 position_pm_highlight()。
    """
    v = pm_cache.get(ticker) or {}
    if not v.get("pos_alert"):
        return ""
    parts = []
    p = v.get("pm_pct")
    if p is not None and abs(p) >= 3.0:
        parts.append("%+.1f%%" % p)
    r = v.get("vol_ratio_pm")
    if r is not None and r >= 0.10:
        parts.append("量比%.0f%%" % (r * 100))
    return "盘前异动 " + "·".join(parts) if parts else ""


def position_pm_highlight(pm_cache: dict, ticker: str) -> str:
    """持仓行的底色：**方向决定颜色**，不再一律标红（2026-08-07 Vic 指出）。

    绿(bull)=盘前上涨、红(warn)=盘前下跌、蓝(band)=只有量异动没有价异动
    （量大但价没动，是"要看一眼"不是"好/坏"——正是 SYK 那次的形态，
    给中性色反而更醒目，不会被当成普通的涨跌）。
    未触发 pos_alert 返回空串。配色语义遵 CONTEXT：绿/红=好/坏、蓝=发生了什么。
    """
    v = pm_cache.get(ticker) or {}
    if not v.get("pos_alert"):
        return ""
    p = v.get("pm_pct")
    if p is None or abs(p) < 3.0:
        return "band"
    return "bull" if p > 0 else "warn"


def x_watch_rows(cache: dict, pm_cache: dict = None, spike_pct: float = 4.0) -> list:
    """X台账定价表骨架：[提及日, 账号, TICKER, 提及时价, 最新收盘, 自提及%, 备注]，按自提及%降序。
    盘前时若给pm_cache，会在备注前加⚡标注当日盘前大幅异动的标的。
    **展示过滤：** ①提及日距报告当天>14天（2026-07-28 Vic："只追踪2周"）；
    ②自提及%≤-7%且已过3个自然日（Vic："暴跌7%以上3天内不拉回来的算失效，3天后删除记录"）；
    ③提及日≥7天且pct_since<0（2026-07-16 Vic："一周前的，跌的标的删除，去弱留强"）。
    命中任一条即不展示——只影响这个渲染表，不删data/x_watch.json主账本本身（长期统计
    每个trader胜率还是要用完整历史，不能survivorship bias），所以别用这个函数的输出结果反推
    "谁被删了trader就不准"，账本一直是全的。"""
    from datetime import date as _date
    report_date = cache.get("data_date")
    report_d = _date.fromisoformat(report_date) if report_date else None
    rows = []
    for it in sorted(cache.get("x_watch_performance", []), key=lambda x: -(x.get("pct_since") or -999)):
        pct = it.get("pct_since")
        if report_d is not None:
            try:
                age_days = (report_d - _date.fromisoformat(it["date"])).days
            except ValueError:
                age_days = 0
            # 展示过滤三条（2026-07-28 Vic："我们只追踪2周吧，暴跌7%以上3天内不拉回来的
            # 算失效，3天后删除记录"）。"暴跌7%"按**自提及%**口径（这张表衡量的就是这个），
            # 不是单日跌幅——单日跌7%但已拉回的不该被删掉。
            if age_days > 14:                                   # ①超出2周追踪窗口
                continue
            if pct is not None and pct <= -7 and age_days >= 3:  # ②暴跌≥7%且3天未拉回=失效
                continue
            if age_days >= 7 and pct is not None and pct < 0:    # ③原「去弱留强」规则保留
                continue
        # 2026-08-07 Vic 抓到：「'一直在看但没下手'；6/26称URI是被低估的数据中心概念，现在被市场」
        # ——句子被 [:36] 硬切在半句上，读者根本不知道"被市场"后面是什么。
        # 备注列本来就有 38% 的宽度，截断的理由（怕表格撑爆）不成立。
        # **改成不截断**；真有超长的交给 CSS 换行，宁可行高不齐也不要断句。
        note = it.get("note") or ""
        if pm_cache:
            pmv = (pm_cache.get(it["ticker"]) or {}).get("pm_pct")
            if pmv is not None and abs(pmv) > spike_pct:
                note = "⚡盘前%+.1f%%！" % pmv + note
        rows.append([it["date"], it["handle"], it["ticker"], str(it["ref_price"]),
                     str(it.get("last_close", "-")), fpct(pct), note])
    return rows


TRADEBOOK_PATH = ROOT / "data" / "tradebook.json"


def load_tradebook_positions(account: str = None) -> list:
    """从Vic自己维护的data/tradebook.json派生当前持仓（2026-07-16 Vic："以后持仓，只扫描我的
    tradebook"——取代之前LongBridge MCP+moomoo CSV的核对流程。那套流程反复因moomoo CSV陈旧漏单
    （2026-07-15一次漏掉DT/RDDT/FTRE平仓+DUOL开仓四笔），tradebook是Vic自己同步更新的，比任何
    外部对账都更及时——2026-07-16验证：ASTH当天止损离场这笔，tradebook里当天中午就有记录，
    比等盘后MCP核对快得多。
    只看status=="open"的trade：qty=买腿股数之和减卖腿股数之和（处理peel减仓）；
    cost=买腿的数量加权均价；stop=stop_history最后一条（没有则退回stop_initial）。
    返回跟positions.json旧格式兼容的dict列表，可以直接喂给positions_rows()：
    {"ticker","account","qty","cost","stop","thesis","status":"ACTIVE"}。
    thesis取值优先级：thesis字段 > entry_logic字段 > （mentor==true时给"【mentor跟单】机械跟随，
    无个人logic"，否则"待Vic补录"）——跟单类仓位没有个人logic是设计如此不是缺失，见CONTEXT.md
    「持仓论点跟踪」。
    ⚠️ 已知缺口：tradebook.json里没有的持仓（比如2026-07-16时点的XSW/IGV）不会出现在这里——
    只扫描tradebook意味着Vic没录的仓位就不会被监控到，这是这条新规则的代价，需要Vic自己保证
    及时录入，Claude不再用LongBridge MCP交叉核实兜底。"""
    d = json.loads(TRADEBOOK_PATH.read_text(encoding="utf-8"))
    out = []
    for t in d["trades"]:
        if t["status"] != "open":
            continue
        if account and t["account"] != account:
            continue
        # 跳过TradeBook UI误建的空行（ticker空/腿价None/qty全0）——2026-07-17实测踩到一条
        # {"ticker":"","legs":[{"buy",0,None}]}导致整个函数崩溃，防御性过滤而不是报错中断
        if not t.get("ticker"):
            continue
        legs = [l for l in t.get("legs", []) if l.get("qty") and l.get("price") is not None]
        if not legs:
            continue
        t = dict(t, legs=legs)
        buy_qty = sum(l["qty"] for l in t["legs"] if l["action"] == "buy")
        sell_qty = sum(l["qty"] for l in t["legs"] if l["action"] == "sell")
        qty = buy_qty - sell_qty
        buy_cost = sum(l["qty"] * l["price"] for l in t["legs"] if l["action"] == "buy")
        cost = round(buy_cost / buy_qty, 4) if buy_qty else None
        stop = t["stop_history"][-1]["stop"] if t.get("stop_history") else t.get("stop_initial")
        thesis = t.get("thesis") or t.get("entry_logic")
        if not thesis:
            thesis = "【mentor跟单】机械跟随，无个人logic" if t.get("mentor") else "待Vic补录"
        out.append({"ticker": t["ticker"], "account": t["account"], "qty": qty, "cost": cost,
                     "stop": stop, "thesis": thesis, "status": "ACTIVE"})
    return out


def positions_rows(positions: list, cache: dict, extra_price_lookup: dict = None) -> list:
    """持仓表骨架：[TICKER, 现价, 成本, 距止损, 持有理由, 失效条件, ""]——判断列留空手写。
    现价优先从cache["metrics"]取，取不到的（非标准universe标的）从extra_price_lookup取。"""
    M = cache["metrics"]
    rows = []
    for p in positions:
        tk = p["ticker"]
        px = (M.get(tk) or {}).get("close")
        if px is None and extra_price_lookup:
            px = extra_price_lookup.get(tk)
        stop = p.get("stop")
        dist = None
        if px is not None and stop:
            dist = round((px - stop) / px * 100, 1)
        # 2026-08-11：成本/止损一律 2 位小数。QA 的「小数位统一2位」原来天天报警没人改——
        # tradebook 里的成本是加权平均，天生带 4~6 位，之前直接 str() 就漏进报告了
        cost = p.get("cost", "-")
        cost_s = ("%.2f" % cost) if isinstance(cost, (int, float)) else str(cost)
        stop_s = ("%.2f" % stop) if isinstance(stop, (int, float)) else str(stop)
        rows.append([tk, str(px if px is not None else "-"), cost_s,
                     ("止损%s距%s%%" % (stop_s, ("%+.1f" % dist) if dist is not None else "-")) if stop else "无止损",
                     p.get("thesis", ""), p.get("invalidation", ""), ""])
    return rows


# =========================================================================
# 今日执行转换（2026-07-23建，Vic："判断对了，但是落实和买法，其实你没有和setup结合起来，
# 预测对了，我却不知道怎么做"）
#
# 这是报告里一直缺的中间层：上面是regime判断、下面是候选清单，两张皮，没有"所以具体做什么"。
# "9EMA企稳"这种写法盘中根本没法执行——必须变成具体价格、具体股数、具体放弃条件。
#
# 三层：
#   ①regime_setup_permission()  regime → 今天哪类setup能做/不能做
#   ②exec_rows()                候选 → 触发价/止损/每股风险/股数/今日状态判定
#   ③进场后检查点写在报告note里（T+1收盘位置<30%减半 / T+3看setup_track / 板块联动）
# =========================================================================

def regime_setup_permission(cache: dict, vol_trend: str = None) -> list:
    """①regime → setup类型准入。返回[(setup类型, 准入, 理由)]。

    判据全部来自cache里已有的数字，不需要额外抓数：
    - 大盘量比：全场量能萎缩时 Setup E(shakeout+burst)的burst定义无法成立
    - 板块单日极差：极差大=个股放大效应强=突破类失败率上升
    - 防御vs进攻板块方向：决定回踩类优先做哪一侧
    """
    M = cache.get("metrics", {})
    out = []

    # 量能：用SPY/QQQ/SMH的量比均值代表全场参与度
    vols = [M.get(t, {}).get("vol_ratio") for t in ("SPY", "QQQ", "SMH")]
    vols = [v for v in vols if v]
    avg_vol = sum(vols) / len(vols) if vols else None

    # 板块单日极差
    XL = ["XLK", "XLV", "XLF", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
    day = [M.get(t, {}).get("t1_pct") for t in XL]
    day = [d for d in day if d is not None]
    spread = (max(day) - min(day)) if day else None

    if avg_vol is not None:
        if avg_vol < 0.75:
            out.append(("Setup E（shakeout+burst）", "🔴今日不可执行",
                        f"全场量比均值仅{avg_vol:.2f}×——burst的定义就是放量，量能萎缩时这类候选只能观察不能进场"))
        else:
            out.append(("Setup E（shakeout+burst）", "✅可做",
                        f"全场量比均值{avg_vol:.2f}×，具备出现放量确认bar的条件"))

    if spread is not None:
        if spread >= 2.0:
            out.append(("Setup B/Base Breakout（突破类）", "🔴今日不做",
                        f"板块单日极差{spread:.2f}pct（个股通常放大板块1.7-2.7×）——"
                        f"高换手轮动环境下突破后squat概率显著上升，实证胜率27%已是全部setup里最差"))
        else:
            out.append(("Setup B/Base Breakout（突破类）", "⚠️降级半仓",
                        f"板块极差{spread:.2f}pct尚可，但突破类实证胜率27%本就最低，不给正常仓位"))

    # 防御vs进攻方向
    defen = [M.get(t, {}).get("t1_pct") for t in ("XLU", "XLP", "XLV")]
    offen = [M.get(t, {}).get("t1_pct") for t in ("XLK", "XLY", "XLC")]
    defen = [d for d in defen if d is not None]
    offen = [d for d in offen if d is not None]
    if defen and offen:
        dm, om = sum(defen) / len(defen), sum(offen) / len(offen)
        side = "防御侧（XLU/XLP/XLV/XLE）" if dm > om else "进攻侧（XLK/XLY/XLC）"
        out.append(("Setup A/D（回踩类）", f"✅优先做{side}",
                    f"防御均值{dm:+.2f}% vs 进攻均值{om:+.2f}%——回踩买点只在资金流入的那一侧才有跟进买盘"))
    return out


def fetch_exec_metrics(tickers: list) -> dict:
    """给不在cache universe里的个股现算执行所需指标。
    cache["metrics"]只覆盖~81只宏观/板块ETF+持仓+ML Leader，而候选大多是方法2挑出来的个股
    ——跟Setup A专项对账"现价开天窗"是同一类问题，这里直接补齐而不是留空。"""
    import importlib
    F = importlib.import_module("fetch_market_data")
    from longport.openapi import QuoteContext, Config
    ctx = QuoteContext(Config.from_apikey_env())
    out = {}
    for t in tickers:
        bars = F.fetch_bars(ctx, t, 60)
        if bars:
            out[t] = F.analyze(bars)
    return out


EXEC_HEADERS = ["TICKER", "收盘", "距20EMA", "距50MA", "收盘位置", "今日状态判定",
                "触发价", "止损", "每股风险", "风险%", "够1×ATR?", "股数"]
RISK_BUDGET = 400.0   # Vic 2026-07-23定：单笔风险预算$400


def exec_rows(cache: dict, tickers: list, risk_budget: float = RISK_BUDGET,
              extra: dict = None, autofetch: bool = True) -> list:
    """②候选 → 可执行指令。表头见EXEC_HEADERS。

    **均线口径2026-07-23改（Vic："距9EMA改成距离20ema/50ma先"）：** 轮动市里9EMA太贴、
    单日板块极差能到12.94pct，9EMA回踩买点天天被噪音打穿；改用20EMA做主判据、50MA做结构参照。

    今日状态判定（核心列，把"并列的4个候选"变成"今天只有1个能碰"）：
      跌破20EMA       → 🔴回踩论点已破
      收盘位置<20%    → 🔴收在当日最低区=还在跌，不是企稳
      收盘位置>80%    → ⚠️收在当日最高区=今天已跑完，谈不上回踩买点
      距20EMA>4%      → ⚠️延伸过度（20EMA比9EMA远，阈值相应从3%放到4%）
      跌破50MA        → 附加⚠️标注：中期结构也破了，即使短线在20EMA上也降级

    触发价=5日高点（突破确认进场，客观可执行）；止损=5日低点-0.5×ATR。
    「够1×ATR?」列：止损距离若不足1×ATR14，正常波动就能打掉——实证Vic 10笔持仓有6笔踩这个坑。
    股数=risk_budget÷每股风险，止损放宽时仓位自动缩小，单笔风险恒定。
    """
    M = dict(cache.get("metrics", {}))
    if extra:
        M.update(extra)
    missing = [t for t in tickers if t not in M or not M[t].get("ema20")]
    if missing and autofetch:
        M.update(fetch_exec_metrics(missing))

    rows = []
    for t in tickers:
        d = M.get(t) or {}
        c, e20, ma50 = d.get("close"), d.get("ema20"), d.get("ma50")
        atr, rp = d.get("atr14"), d.get("range_pos")
        if c is None or e20 is None or atr is None:
            rows.append([t, "-", "-", "-", "-", "🔴数据缺失，需人工补", "-", "-", "-", "-", "-", "-"])
            continue
        d20 = (c / e20 - 1) * 100
        d50 = ((c / ma50 - 1) * 100) if ma50 else None

        if d20 < 0:
            verdict = f"🔴买点作废：已跌破20EMA {e20:.2f}"
        elif rp is not None and rp < 20:
            verdict = f"🔴买点作废：收在当日最低区（{rp}%），还在跌不是企稳"
        elif rp is not None and rp > 80:
            verdict = f"⚠️今天已跑完（收盘位置{rp}%），等回到20EMA {e20:.2f}再看"
        elif d20 > 4:
            verdict = f"⚠️延伸过度（距20EMA{d20:+.2f}%），只做回踩不追"
        else:
            verdict = f"✅仍在买点区（距20EMA{d20:+.2f}%、收盘位置{rp}%）"
        if d50 is not None and d50 < 0 and not verdict.startswith("🔴"):
            verdict += f"｜⚠️但已在50MA下方{d50:+.2f}%，中期结构未修复"

        hi5, lo5 = d.get("hi5"), d.get("lo5")
        if hi5 and lo5:
            entry, stop = hi5, lo5 - 0.5 * atr
        else:
            entry, stop = c + 0.5 * atr, c - 1.5 * atr
        risk = entry - stop
        atr_mult = risk / atr if atr else 0
        atr_ok = f"✅{atr_mult:.1f}×" if atr_mult >= 1.0 else f"🔴仅{atr_mult:.1f}×"
        shares = int(risk_budget / risk) if (risk_budget and risk > 0) else None
        rows.append([t, f"{c:.2f}", f"{d20:+.2f}%",
                     (f"{d50:+.2f}%" if d50 is not None else "-"),
                     f"{rp}%" if rp is not None else "-", verdict,
                     f"{entry:.2f}", f"{stop:.2f}", f"{risk:.2f}",
                     f"{risk / entry * 100:.2f}%", atr_ok, str(shares) if shares else "-"])
    return rows


# =========================================================================
# 🔴 成交量的读法取决于它出现在哪个位置（2026-08-05 Vic 定，「这个加入我们的框架，
#    不要只记住，我觉得很重要」）
#
# 同一个「缩量」在不同位置含义完全相反，这是 2026-08-04 我读错 8/3 那根 bar 的根因：
#   · 回踩／整理／rally attempt 期缩量 = **无供给**（没人卖）= 加分
#       —— Wyckoff no supply bar、Minervini VDU(volume dry-up)、我们的 Setup A 就是这个
#   · 突破／确认日（FTD、Setup B/E 的 burst bar）缩量 = **无需求**（没人买）= 减分
#       —— O'Neil 要看到机构真金白银进场；实测见 CONTEXT.md「FTD 日的量能不能反着读」
#
# **不要再靠人每次记住**：所有输出量比的地方一律走 volume_read()，让读法跟着位置自动出来。
# 新增用到量比的表 → 传对 context，别自己写判断文字。
VOL_CONTEXT = {
    "pullback":  ("缩量=无供给", "放量=有人在卖"),   # 回踩/整理/Setup A/D
    "attempt":   ("缩量=卖压枯竭", "放量=仍在换手"),  # rally attempt 的 Day 2-3
    "breakout":  ("缩量=无需求", "放量=需求进场"),    # 突破/FTD/burst bar
    # 🔴 base：只有 W（双底/三重底）这类**结构标记**、没有入场时点含义时用它。
    # 2026-08-05 首日就踩到：W 被默认按 pullback 读，导致 8/4 放量突破的 ANET/AAOI/MRVL
    # 全被标成「放量=有人在卖」。**不知道这根bar是在等待还是在确认时，就不要给好坏判断**——
    # 只描述，把结论留给看图的人。
    "base":      ("缩量", "放量"),
}
VOL_GOOD_WHEN_LOW = {"pullback", "attempt"}
VOL_NO_VERDICT = {"base"}


def volume_read(context: str, vol_ratio, low=0.9, high=1.2):
    """把量比翻译成「在这个位置上是加分还是减分」。

    context: pullback / attempt / breakout（见 VOL_CONTEXT）
    返回 (kind, text)，kind ∈ {"good","bad","flat"}；text 已含量比数字，直接进表格。
    """
    if vol_ratio is None:
        return "flat", "-"
    lo_txt, hi_txt = VOL_CONTEXT.get(context, VOL_CONTEXT["breakout"])
    good_low = context in VOL_GOOD_WHEN_LOW
    if vol_ratio <= low:
        kind, note = ("good" if good_low else "bad"), lo_txt
    elif vol_ratio >= high:
        kind, note = ("bad" if good_low else "good"), hi_txt
    else:
        kind, note = "flat", "量能中性"
    if context in VOL_NO_VERDICT:          # 结构标记：只描述不判好坏
        kind = "flat"
    mark = {"good": "＋", "bad": "－", "flat": "·"}[kind]
    return kind, "%.2fx %s %s" % (vol_ratio, mark, note)


def setup_context(tags: str) -> str:
    """由 Setup 标签推出该看哪种量。
    B（突破整理）/ E（shakeout+burst 已确认）= 突破类，要放量；
    A（缩量回踩9EMA）/ C（undercut收回）/ D（突破后缩量回踩）/ Ew（burst未确认）= 回踩类，要缩量；
    **只有 W（双底/三重底）= 结构标记，没有入场时点含义 → base，只描述不判好坏**。
    多标签共存时以突破类优先（那根 bar 的性质决定该看什么量）。"""
    parts = [p.strip() for p in (tags or "").replace("Ew", "w").split("+") if p.strip()]
    if any(p in ("B", "E") for p in parts):
        return "breakout"
    if any(p in ("A", "C", "D", "w") for p in parts):
        return "pullback"
    return "base"


def setup_scan_rows(setups_cache: dict, cache: dict = None, sectors: list = None) -> list:
    """方法2/8机器初筛结果骨架：
    [TICKER, 板块归属, Setup标签, RS(1周), 距9EMA, 距20MA(ATR), 量比, 机器说明]。
    - 排序：按板块分组、强势板块在前（板块ETF的5日RS降序，watchlist兜底票垫底），组内按个股5日RS降序
    - RS列取代原RSI列（Vic：看RS不是RSI），只用1周口径
    - 仓位/许可不再逐行标注，统一写在表后的strong_sector_setups_permission提醒里
    sectors给定时只保留归属含这些板块的标的（方法2下钻用）。仍需人眼过滤趋势背景后才能入ABC候选。"""
    M = (cache or {}).get("metrics", {})
    q = M.get("QQQ") or {}

    def stock_rs5(r):
        a, b = r.get("d5_pct"), q.get("d5_pct")
        return None if (a is None or b is None) else round(a - b, 2)

    # 板块强弱排名：出现过的板块ETF按其5日RS降序；watchlist兜底票排所有板块之后
    etf_rs5 = {}
    for tk, r in setups_cache.get("hits", {}).items():
        for e in r.get("sector_etfs", []):
            if e not in etf_rs5:
                em = M.get(e) or {}
                v = None if (em.get("d5_pct") is None or q.get("d5_pct") is None) else em["d5_pct"] - q["d5_pct"]
                etf_rs5[e] = v
    ranked = sorted([e for e in etf_rs5], key=lambda e: -(etf_rs5[e] if etf_rs5[e] is not None else -999))
    sector_rank = {e: i for i, e in enumerate(ranked)}

    items = []
    for tk, r in setups_cache.get("hits", {}).items():
        if sectors and not any(e in sectors for e in r.get("sector_etfs", [])):
            continue
        rs5 = stock_rs5(r)
        etfs = r.get("sector_etfs", [])
        rank = min((sector_rank.get(e, 999) for e in etfs), default=999)
        tags = "+".join(s["type"] for s in r["setups"])
        items.append((rank, -(rs5 if rs5 is not None else -999),
                      [tk, "/".join(etfs) or "-", tags, rs_num(rs5),
                       fpct(r.get("dist_ema9_pct")),
                       ("%.2f" % r["dist_ma20_atr"]) if r.get("dist_ma20_atr") is not None else "-",
                       # 🔴量比列走 volume_read()：读法跟着 setup 类型自动切换，
                       # 回踩类缩量是加分、突破类缩量是减分，不再是一个裸数字
                       volume_read(setup_context(tags), r.get("vol_ratio"))[1],
                       "；".join(s["note"] for s in r["setups"])]))
    items.sort(key=lambda x: (x[0], x[1]))
    return [it[2] for it in items]


# ---------------- 候选跟踪台账（2026-07-15建，见CONTEXT.md「Setup A专项对账」+「02主线复盘候选跟踪」）
# 一个台账文件（data/setup_track.json）喂两处消费：①Setup A专项对账——只看setup标签含"A"的条目，
# 持续跟踪到D+N判定hit/partial/miss，攒样本评估这个setup的真实胜率；②02主线复盘候选跟踪——不限
# setup类型，滚动展示窗口内点过名的全部A级候选（2026-07-15 Vic："追踪要连续3日"）。
SETUP_TRACK_PATH = ROOT / "data" / "setup_track.json"

# 跟踪窗口（交易日）。2026-07-28定为3天；2026-08-07 Vic改为5天——3天太短，
# 不少setup还没走出方向就被判expired（历史39条里12条是expired，占比太高）。
# 想再调只改这一个常量：setup_a_track_rows的窗口/状态标签、expire_stale_track_entries的默认值都读它。
SETUP_TRACK_WINDOW = 5


def _load_setup_track() -> dict:
    if SETUP_TRACK_PATH.exists():
        return json.loads(SETUP_TRACK_PATH.read_text(encoding="utf-8"))
    return {"entries": []}


def _save_setup_track(ledger: dict) -> None:
    SETUP_TRACK_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")


def _is_setup_a(text) -> bool:
    text = text or ""
    if any(h in text for h in ("Setup A", "缩量回踩9EMA", "回踩9EMA")):
        return True
    return "A" in [t.strip() for t in text.split("+")]


def _trading_dates(cache: dict) -> list:
    dates = {p.stem.replace("-postmarket", "") for p in (ROOT / "data" / "daily").glob("*-postmarket.json")}
    if cache.get("data_date"):
        dates.add(cache["data_date"])
    return sorted(dates)


INVALID_MIN_BUFFER_ATR = 0.5      # 失效位距结构位的最小缓冲（ATR倍数）
INVALID_MIN_BUFFER_PCT = 1.0      # 或最小缓冲百分比，两者取宽松的那个


def _first_number(text):
    """从"跌破40.1(三重底L1)"这类自由文本里取第一个价格数字；取不到返回None。"""
    m = re.search(r"(\d+(?:\.\d+)?)", str(text or ""))
    return float(m.group(1)) if m else None


def check_invalid_level(ticker: str, date_str: str, invalid, ctx=None):
    """校验失效位（2026-07-30建，源于21条台账复盘的两个真实事故）。

    **FIS（7/22判miss）**：失效位设在三重底L1的精确值40.10、零缓冲，7/23收盘40.04
    只破了0.15%就判miss，随后涨到46.81（+15.5%）。
    **AJG（7/15判miss）**：失效位250，而信号日当天最低价就是246.35——**建仓时就已经失效**。

    两条判定按当时的规则都没错，是规则本身有问题：miss数会系统性虚高，
    让人误以为是选票差，实际是止损被噪音打掉/一开始就设错。

    返回错误信息字符串（有问题）或None（通过）。只在能从invalid里解析出价格时才校验；
    "跌破9EMA不收回"这类相对表述跳过（无法在盘前定值，由盘后按实际9EMA判）。
    """
    lv = _first_number(invalid)
    if lv is None:
        return None
    try:
        from longport.openapi import QuoteContext, Config, Period, AdjustType
        ctx = ctx or QuoteContext(Config.from_apikey_env())
        bars = [b for b in ctx.candlesticks(f"{ticker}.US", Period.Day, 30,
                                            AdjustType.NoAdjust)
                if str(b.timestamp.date()) <= date_str]
        if not bars:
            return None
        day = bars[-1]
        low, close = float(day.low), float(day.close)
        trs = [max(float(b.high) - float(b.low),
                   abs(float(b.high) - float(bars[i - 1].close)),
                   abs(float(b.low) - float(bars[i - 1].close)))
               for i, b in enumerate(bars) if i > 0]
        atr = sum(trs[-14:]) / max(len(trs[-14:]), 1) if trs else None
    except Exception as e:
        return f"{ticker}: 失效位无法校验（取数失败 {e}）"

    if lv >= low:
        return (f"{ticker}: 失效位 {lv:g} **不低于信号日最低价 {low:.2f}**——"
                f"建仓即失效（AJG 2026-07-15 就是这么变成miss的）。"
                f"请把失效位下移到 {low:.2f} 之下并留缓冲")
    buf_pct = (low - lv) / low * 100
    need = max(atr * INVALID_MIN_BUFFER_ATR, low * INVALID_MIN_BUFFER_PCT / 100) if atr else None
    if need and (low - lv) < need:
        return (f"{ticker}: 失效位 {lv:g} 距信号日最低价 {low:.2f} 仅 {buf_pct:.2f}%"
                f"（需 ≥{need / low * 100:.2f}% = max(0.5ATR, 1%)）——"
                f"缓冲太薄会被噪音打掉（FIS 2026-07-22 只破0.15%就判miss，随后涨15.5%）")
    return None


def sync_candidate_track(date_str: str, watchlist_abc: list = None,
                         watchlist_a: list = None, check_levels: bool = True) -> int:
    """把当天A级候选（不限setup类型）写进data/setup_track.json台账（去重by date+ticker）。
    在assemble脚本写完out字典、json.dump之前调用一次：
    H.sync_candidate_track(DAY, out.get("watchlist_abc"), out.get("watchlist_a"))。返回新增条数。
    - watchlist_abc：只收grade以'A'开头的（B/C是"只看不做"，不值得占跟踪表位置）
    - watchlist_a：CONTEXT.md定义里本来就是A级候选，全收
    - 每条记录真实的grade/source/setup标签（source=候选来自CONTEXT.md「机会扫描」哪个方法，
      如"方法2"/"方法8·Vic肉眼"/"X trader"——watchlist_a/abc条目建议都带上source字段，
      不带则记"-"，02主线复盘候选跟踪表的"来源"列会跟着显示"-"）
    - setup字段含"A"（含Setup A/缩量回踩9EMA/回踩9EMA字样，或机器标签按+拆分恰好有"A"）的条目
      同时会出现在Setup A专项对账里——这就是两处共用一个台账的机制"""
    ledger = _load_setup_track()
    seen = {(e["date"], e["ticker"]) for e in ledger["entries"]}
    added = 0
    problems = []

    def add(ticker, grade, source, sector, entry, invalid, target, setup_tag):
        nonlocal added
        if not ticker or (date_str, ticker) in seen:
            return
        ledger["entries"].append({
            "date": date_str, "ticker": ticker, "grade": grade or "A", "source": source or "-",
            "setup": setup_tag or "-", "sector": sector or "-",
            "entry": entry, "invalid": invalid, "target": target,
            "status": "tracking", "verdict": None,
        })
        seen.add((date_str, ticker))
        added += 1
        # 失效位硬校验（2026-07-30 Vic："改"）——写进台账前就查，不合规直接抛。
        # 不做警告了事：警告会被忽略，而失效位设错的代价是miss数虚高、方法论被误判。
        if check_levels:
            msg = check_invalid_level(ticker, date_str, invalid)
            if msg:
                problems.append(msg)

    for it in (watchlist_abc or []):
        grade = str(it.get("grade", ""))
        if grade.startswith("A"):
            add(it.get("ticker"), grade, it.get("source"), it.get("sector"),
                it.get("entry"), it.get("invalid"), it.get("target"), it.get("setup"))
    for it in (watchlist_a or []):
        add(it.get("ticker"), "A", it.get("source"), it.get("sector"),
            it.get("entry"), it.get("invalid"), it.get("target"), it.get("setup") or it.get("why"))

    if problems:
        raise ValueError(
            "失效位设置不合规，未写入台账（2026-07-30起硬校验，见 check_invalid_level 文档）：\n  - "
            + "\n  - ".join(problems)
            + "\n改对失效位后重跑；确实要先落盘可传 check_levels=False，但请在报告里写明原因。")
    if added:
        _save_setup_track(ledger)
    return added


def setup_a_track_rows(cache: dict, extra_prices: dict = None):
    """Setup A专项对账用：返回(rows, due)，只看setup标签含"A"的条目。
    2026-07-28 Vic：「只跟踪3天，超过3天的不用继续追踪了，只留记录就好」；
    **2026-08-07 Vic改为5个交易日**（3天窗口太短，很多setup还没走出来就被判过期）。
    窗口长度统一由模块常量 SETUP_TRACK_WINDOW 控制，改一处即可。
    **rows只含仍在窗口内的条目**（elapsed<窗口 或今天刚好到期待评定）；
    已结案/超窗的进历史，由 build_tradebook.py 渲染成TradeBook的「Setup A 历史」标签页。
    列=[信号日,TICKER,板块,入场,失效,目标,现价,累计%,状态]。
    due=刚好满窗口天数、status仍是tracking、需要Claude今天给verdict的条目
    [{"date":,"ticker":,"pct_since_signal":}]——判定后调close_setup_track_entries()写回。
    **现价查找（2026-07-16修复，Vic抓到"你怎么都没填现价"）：** cache["metrics"]只覆盖
    fetch_market_data.py的~88只宏观/板块ETF+持仓+ML Leader，Setup A候选大多是方法2/8挑出来的
    个股，压根不在这个窄universe里，之前直接查cache必定是"-"。extra_prices是调用方传入的
    {ticker: close}补充查找表（当天用quick_quote.py或LongPort SDK现查setup_track里所有
    status=tracking的ticker，缺一个查一个，不能再让这张表大面积开天窗）。"""
    ledger = _load_setup_track()
    trading_dates = _trading_dates(cache)
    M = cache["metrics"]
    extra_prices = extra_prices or {}
    rows, due = [], []
    for e in ledger["entries"]:
        if not _is_setup_a(e.get("setup", "")):
            continue
        elapsed = sum(1 for d in trading_dates if d > e["date"])
        cur = (M.get(e["ticker"]) or {}).get("close")
        if cur is None:
            cur = extra_prices.get(e["ticker"])
        entry_px = e.get("entry")
        pct_since = None
        try:
            if cur is not None and entry_px not in (None, "", "-"):
                pct_since = round((float(cur) - float(entry_px)) / float(entry_px) * 100, 2)
        except (TypeError, ValueError):
            pass
        if e.get("verdict"):
            status_label = e["verdict"]
        elif e.get("status") == "tracking":
            status_label = (f"待评定(D+{SETUP_TRACK_WINDOW})" if elapsed >= SETUP_TRACK_WINDOW
                            else f"跟踪中(D+{elapsed})")
        else:
            status_label = e.get("status", "-")
        # 只有还在窗口内（含今天到期待评定）的才进报告表；其余只留在台账里当历史
        if e.get("status") == "tracking" and elapsed <= SETUP_TRACK_WINDOW:
            rows.append([e["date"], e["ticker"], e.get("sector", "-"), str(entry_px), str(e.get("invalid", "-")),
                         str(e.get("target", "-")), str(cur if cur is not None else "-"),
                         fpct(pct_since), status_label])
        if e.get("status") == "tracking" and elapsed >= SETUP_TRACK_WINDOW:
            due.append({"date": e["date"], "ticker": e["ticker"], "pct_since_signal": pct_since})
    return rows, due


def expire_stale_track_entries(cache: dict, window: int = None) -> int:
    """2026-07-28 Vic：「超过3天的不用继续追踪了，只留记录就好」（2026-08-07窗口改为5个交易日）。
    超过window个交易日仍是tracking、且从未被判定的条目，给一个诚实的终态：
    status=closed / verdict="expired"（过期未评定）——**不替它们编造hit/miss**，
    因为当时没做判定，事后按价格倒推等于用后见之明打分。返回处理条数。"""
    if window is None:
        window = SETUP_TRACK_WINDOW
    ledger = _load_setup_track()
    dates = _trading_dates(cache)
    n = 0
    for e in ledger["entries"]:
        if e.get("status") != "tracking" or e.get("verdict"):
            continue
        if sum(1 for d in dates if d > e["date"]) > window:
            e["status"] = "closed"
            e["verdict"] = "expired"
            n += 1
    if n:
        _save_setup_track(ledger)
    return n


def setup_track_history(cache: dict) -> list:
    """已结案条目（供TradeBook的「Setup A 历史」标签页）。newest first。"""
    ledger = _load_setup_track()
    dates = _trading_dates(cache)
    out = []
    for e in ledger["entries"]:
        if e.get("status") != "closed":
            continue
        out.append({"date": e["date"], "ticker": e["ticker"], "setup": e.get("setup", ""),
                    "sector": e.get("sector", ""), "entry": e.get("entry"),
                    "invalid": e.get("invalid"), "target": e.get("target"),
                    "verdict": e.get("verdict", "-"), "source": e.get("source", "")})
    return sorted(out, key=lambda x: (x["date"], x["ticker"]), reverse=True)


def close_setup_track_entries(verdicts: dict) -> None:
    """verdicts: {(date,ticker): "hit"/"partial"/"miss"}。盘后assemble给due里每条判完verdict后调用，
    标记status=closed并写回data/setup_track.json，之后不再出现在"待评定"里。
    判断建议：close收在target之上或累计%明显为正→hit；跌破invalid止损位→miss；两者之间→partial。"""
    ledger = _load_setup_track()
    changed = False
    for e in ledger["entries"]:
        key = (e["date"], e["ticker"])
        if key in verdicts:
            e["verdict"] = verdicts[key]
            e["status"] = "closed"
            changed = True
    if changed:
        _save_setup_track(ledger)


# ---------------------------------------------------------------------------
# S&P500全量市宽（2026-07-21接入，Vic主Sheet新tab「S&P 500 LIVE MARKET BREADTH」）
# 数据由fetch_market_data.fetch_sp500_breadth()写进cache["sp500_breadth"]
# ---------------------------------------------------------------------------

_BREADTH_SIGNAL_BADGE = {
    "Strong": "green", "Positive": "green",
    "Neutral": "blue", "Mixed": "amber",
    "Weak": "red", "Negative": "red",
}

_BREADTH_METRIC_CN = {
    "New Highs vs New Lows": "新高 vs 新低",
    "Advance vs Decline": "上涨 vs 下跌",
    "Up from Open vs Down": "高开走强 vs 走弱",
    "Up on Volume vs Down on Volume": "放量上涨 vs 放量下跌",
    "Up 4% vs Down 4%": "涨4% vs 跌4%",
}

_STAGE_CN = {
    "Stage 1": "Stage 1 筑底",
    "Stage 2": "Stage 2 上升趋势",
    "Stage 3": "Stage 3 顶部派发",
    "Stage 4": "Stage 4 下降趋势",
}


_INTERNALS_SPECS = [
    ("q", "q_up25", "q_dn25", "季度 涨25%+ / 跌25%+", "最慢最重的口径，翻负=趋势级别恶化"),
    ("m25", "m_up25", "m_dn25", "月内 涨25%+ / 跌25%+", "中期动量，反应比季度快一档"),
    ("m50", "m_up50", "m_dn50", "月内 涨50%+ / 跌50%+", "极端涨跌对比，「腰斩股」的直接度量"),
    ("d34", "d34_up13", "d34_dn13", "34日 涨13%+ / 跌13%+", "中短期，噪音比前三个大"),
]


def stockbee_internals(cache: dict, lookback: int = 22):
    """中期广度内核趋势（2026-07-23建）。

    **为什么需要这一节：** 之前判断广度只用T2108和4%涨跌家数——**两个都是短期口径**，
    在指数横盘时会一直显示"中性"。而Stockbee的二级指标（季度/月内/34日的涨跌家数对比）
    衡量的是"到底有多少股票在真的赚钱"，它跟指数可以长期背离。
    实证（Vic 2026-07-23指出）：S&P 6/22→7/22 只涨0.34%，同期
    季度涨25%净值从+472塌到-26、月内涨25%+的只数从302只掉到101只（-67%）。
    **短期口径看到的是"轮动"，中期口径看到的是"单向、不回头的塌陷"——那是分批出货不是轮动。**

    返回 (table, verdict)：verdict含score(0-4，几个中期口径为负)、pool(可赚钱股票池只数)、
    turned(各口径翻负的日期)、note。
    """
    sb = (cache or {}).get("stockbee") or {}
    rows = sb.get("rows") or []
    if not rows:
        return None, {"error": sb.get("error", "cache里没有stockbee数据（需重跑fetch_market_data.py）")}

    seq = list(reversed(rows[:lookback]))     # oldest → newest
    cur, first = seq[-1], seq[0]

    def net(r, up, dn):
        return (r[up] - r[dn]) if (r.get(up) is not None and r.get(dn) is not None) else None

    trows, score, turned = [], 0, {}
    for key, up, dn, label, why in _INTERNALS_SPECS:
        n_cur, n_first = net(cur, up, dn), net(first, up, dn)
        if n_cur is None:
            continue
        if n_cur < 0:
            score += 1
        # 找最近一次由正转负的日期
        flip = None
        for i in range(len(seq) - 1, 0, -1):
            a, b = net(seq[i], up, dn), net(seq[i - 1], up, dn)
            if a is not None and b is not None and a < 0 <= b:
                flip = seq[i]["date"]
                break
        turned[key] = flip
        # 连续为负天数
        streak = 0
        for r in reversed(seq):
            v = net(r, up, dn)
            if v is not None and v < 0:
                streak += 1
            else:
                break
        trows.append([
            label,
            f"{cur[up]:.0f} / {cur[dn]:.0f}",
            f"{n_cur:+.0f}",
            f"{n_first:+.0f}" if n_first is not None else "-",
            f"{n_cur - n_first:+.0f}" if n_first is not None else "-",
            ("🔴已翻负" + (f"（{flip}起，连续{streak}日）" if flip else f"（连续{streak}日）"))
            if n_cur < 0 else "🟢仍为正",
            why,
        ])

    table = {"headers": ["口径", f"最新({cur['date']})", "净值", f"{first['date']}净值",
                         "区间变化", "状态", "含义"],
             "rows": trows, "num_cols": [2, 3, 4]}

    pool_now, pool_then = cur.get("m_up25"), max((r.get("m_up25") or 0) for r in seq)
    pool_chg = ((pool_now / pool_then - 1) * 100) if (pool_now and pool_then) else None
    spx_chg = ((cur["spx"] / first["spx"] - 1) * 100) if (cur.get("spx") and first.get("spx")) else None

    if score >= 3:
        head = "🔴中期内核已塌陷"
    elif score == 2:
        head = "⚠️中期内核转坏"
    elif score == 1:
        head = "中期内核出现裂缝"
    else:
        head = "🟢中期内核完好"

    note = (f"{head}（4个中期口径中 {score} 个为负）。"
            f"**可赚钱股票池：月内涨25%+的只数 {pool_now:.0f} 只，区间内最高 {pool_then:.0f} 只"
            f"（{pool_chg:+.0f}%）**。同期 S&P {spx_chg:+.2f}%。"
            f"——指数与内核的背离幅度就是这两个数字的差。"
            if pool_now and spx_chg is not None else head)

    return table, {"score": score, "pool_now": pool_now, "pool_max": pool_then,
                   "pool_chg": pool_chg, "spx_chg": spx_chg, "turned": turned,
                   "head": head, "note": note, "date": cur["date"]}


def cross_check_alignment(gate_rows: list, breadth_rows: list, risk_items: list) -> dict:
    """三张表（攻守记分板/市宽打分/动能打分）方向一致性检查（2026-07-27 Vic：
    "不知道会不会有不同向的情况，如果不同向，一定要指出"）。

    ⚠️这是**描述性**检查，不是预测性规则——它只回答"这三张表现在指向同一个方向吗"，
    不声称任何胜率或未来收益。（对比同日删掉的「广度背离预警」：那条用2个样本硬定阈值、
    声称能提前预警，59天回测证明无预测力。本函数不设收益阈值、不做触发判定，
    只做三个已有结论之间的对照，因此不存在同类过拟合问题。）

    每张表折算成 bull / neutral / bear：
      - 攻守记分板：任一指数跌破防守线→bear；全部站上进攻线→bull；否则neutral
      - 市宽打分：有降级项triggered→bear；无triggered且有升级项met→bull；否则neutral
      - 动能打分：high档≥4项→bear；≤1项→bull；否则neutral
    返回 {verdict, stances, headline, detail}。verdict ∈ aligned / split。
    """
    # 攻守记分板
    kinds = [r.get("state_kind") for r in gate_rows]
    if "broken" in kinds:
        gate = "bear"
    elif kinds and all(k == "attack" for k in kinds):
        gate = "bull"
    else:
        gate = "neutral"

    # 市宽打分
    trig = [r for r in breadth_rows if r.get("status") == "triggered"]
    met = [r for r in breadth_rows if r.get("status") == "met"]
    if trig:
        breadth = "bear"
    elif met:
        breadth = "bull"
    else:
        breadth = "neutral"

    # 动能打分
    high_n = sum(1 for it in risk_items if it.get("level") == "high")
    momentum = "bear" if high_n >= 4 else ("bull" if high_n <= 1 else "neutral")

    stances = {"攻守记分板": gate, "市宽打分": breadth, "动能打分": momentum}
    ZH = {"bull": "偏多", "neutral": "中性", "bear": "偏空"}
    uniq = set(stances.values())

    if len(uniq) == 1:
        verdict = "aligned"
        headline = f"✅三表同向（均为{ZH[gate]}）"
        detail = ("攻守记分板、市宽打分、动能打分本日指向一致——"
                  "价格位置、广度内部、风险清单三个角度没有互相矛盾，判断可以直接采用。")
    else:
        verdict = "split"
        desc = "、".join(f"{k}={ZH[v]}" for k, v in stances.items())
        headline = f"🔴三表分歧：{desc}"
        pairs = []
        if gate != breadth:
            if gate in ("bull", "neutral") and breadth == "bear":
                pairs.append("**价格位置好于内部结构**（指数还没破位但广度已经在恶化）——"
                             "这是典型的派发/顶部型分歧，价格是滞后项，2026-07-21/22那次就是这个形态："
                             "大盘当天还在涨、SPX>20MA却单日掉3.18pt，两天后QQQ才正式跌破690。"
                             "**这种分歧下，以广度为准、不要用'指数还没破'安慰自己。**")
            elif gate == "bear" and breadth in ("bull", "neutral"):
                pairs.append("**内部结构好于价格位置**（指数破位但广度已在修复）——"
                             "可能是权重股单独受伤拖累指数、而多数个股其实在改善（洗盘/轮动而非全面转空）。"
                             "**这种分歧下不要因为指数破位就全面停手，但也需要价格确认后才加仓。**")
        if momentum != gate or momentum != breadth:
            pairs.append(f"动能打分（{ZH[momentum]}，high档{high_n}项）与另两张表不一致——"
                         "动能打分是定性观感，另两张是定量门槛；**定性与定量打架时以定量为准，"
                         "并回头检查是不是某一项的档位打得太重或太轻。**")
        detail = "；".join(pairs) if pairs else "三表未完全一致，请逐项核对。"

    return {"verdict": verdict, "stances": stances, "high_n": high_n,
            "headline": headline, "detail": detail}


def sp500_breadth_tables(cache: dict, history_days: int = 10):
    """返回 (live_table, stage_table, history_table, meta)。
    meta含score/regime/risk_mode/session/status/updated，以及live与history当日行的差异提示
    （live块是盘后快照、history行是结算值，两者偶有出入——不对齐，各自标明口径）。
    数据缺失时返回(None,None,None,{"error":...})，调用方跳过整节不渲染空壳。"""
    b = (cache or {}).get("sp500_breadth") or {}
    if not b or b.get("error"):
        return None, None, None, {"error": b.get("error", "no sp500_breadth in cache")}

    live = b.get("live", {})
    live_rows = []
    for m in live.get("metrics", []):
        kind = _BREADTH_SIGNAL_BADGE.get(m.get("signal", ""), "blue")
        live_rows.append([
            _BREADTH_METRIC_CN.get(m["metric"], m["metric"]),
            str(m.get("positive", "-")), str(m.get("negative", "-")),
            m.get("positive_pct", "-"),
            ("%+d" % m["net"]) if isinstance(m.get("net"), (int, float)) else "-",
            badge(kind, m.get("signal", "-")),
        ])
    live_table = {"headers": ["指标", "正向", "负向", "正向%", "净值", "信号"],
                  "rows": live_rows, "num_cols": [], "raw_cols": [5]}

    stage_table = {"headers": ["阶段", "只数", "占比"], "rows": [
        [_STAGE_CN.get(s["stage"], s["stage"]), str(s.get("count", "-")), s.get("share", "-")]
        for s in b.get("stages", [])], "num_cols": []}

    hist = b.get("history", [])[:history_days]
    history_table = {"headers": ["日期", "新高/新低", "涨/跌", "涨%", "高开走强/走弱",
                                 "放量涨/跌", "Stage2%", "Stage4%", "综合分"],
                     "rows": [], "num_cols": []}
    for h in hist:
        history_table["rows"].append([
            h["date"], f"{h.get('new_highs','-')}/{h.get('new_lows','-')}",
            f"{h.get('advance','-')}/{h.get('decline','-')}", h.get("advance_pct", "-"),
            f"{h.get('up_open','-')}/{h.get('down_open','-')}",
            f"{h.get('up_volume','-')}/{h.get('down_volume','-')}",
            h.get("stage2_pct", "-"), h.get("stage4_pct", "-"), str(h.get("score", "-")),
        ])

    meta = {"score": live.get("score", "-"), "regime": live.get("regime", "-"),
            "risk_mode": live.get("risk_mode", "-"), "session": live.get("session", "-"),
            "status": live.get("status", "-"), "updated": live.get("updated", "-"),
            "classified": live.get("classified"), "history": hist}
    if hist:
        meta["today_row"] = hist[0]
    return live_table, stage_table, history_table, meta


# =========================================================================
# 盘前两段式接力（2026-07-22 Vic："盘前报告我想每次分两段跑，白天跑隔夜收盘和x账号，
# 4点后跑盘前数据"）
#
# 为什么需要这套东西：省token规则要求每天开新会话跑盘前，两段式=两个会话，段2的会话
# 完全不知道段1想了什么。cache文件只能传递"机械数据"，传不了"判断"——所以段1必须把
# 判断落进 data/daily/YYYY-MM-DD-premarket.json 这份草稿里，段2读草稿续写，不是重做。
# 段2**绝不能**重跑 fetch_market_data.py（收盘数已定，重跑只是浪费+可能污染signal_history）。
# =========================================================================

# 字段分三类，不是两类——因为有一批表格是"段1建好骨架+判断列，段2只补一个盘前列"，
# 硬塞进两分法会导致段2把段1的判断整个重写一遍（那就白分段了）。

# ①段1定稿，段2不动：全部基于上一交易日收盘 + 隔夜新闻 + X扫描
PHASE1_FIELDS = [
    "report_type", "date", "title", "subtitle", "badges",
    "scoreboard_rows", "scoreboard_note", "risk_checklist", "risk_checklist_note",
    "gate_scoreboard_rows", "breadth_score_rows", "breadth_score_note", "cross_check",
    "atr_extension_table", "atr_extension_note",
    "regime_triggers", "breadth_table", "breadth_table_note",
    "other_assets_table", "joint_signal_lines", "macro_radar_table", "macro_radar_detail",
    "unilateral_scan_table", "unilateral_scan_note",
    "ml_leaders", "ml_leaders_note", "leader_vs_defensive_note",
    "adanos_scan_table", "x_sentiment_macro", "x_sentiment_macro_summary",
    "x_sentiment_stocks", "x_sentiment_note",
    "thirteen_dg_rows", "thirteen_dg_note", "squeeze_candidates", "squeeze_note",
    "news_week", "week_calendar", "industry_radar_table", "x_watch_table", "x_watch_note", "footer_sources",
    # 2026-08-04补：这三组字段只依赖「已收盘」数据（FTD计数／仓位治理／反弹队列收盘区间），
    # 本来就是段1产物，但建表时列表没跟着更新——8/3的段1草稿是靠手动往keep里塞才保住的。
    # 不写进这里，换个新会话又会被 keep 过滤掉（静默丢失）。
    "ftd", "ftd_table", "ftd_note",
    "position_governance_table", "position_governance_note",
    "bounce_table", "bounce_note",
    # 2026-08-09 Vic 批的「事件缺口延续」8/6 就通过了，8/7 一个候选都没进报告——
    # 因为字段名不在这张表里，keep() 直接过滤掉了。**新批准的类别必须当天就加进来。**
    # 无条件生成：没有符合的就写「无」，「字段是空的」和「字段不存在」只有前者看得见。
    "event_gap_candidates", "event_gap_note",
    # 🔴 2026-08-11 补：**同一个坑第三次**（前两次是 8/3 的 ftd/仓位治理、8/7 的事件缺口）。
    #    8/07–8/10 陆续加的这一批字段进了 assemble_template.py，却没人把它们加进三个 phase 桶——
    #    后果比前两次更隐蔽：**段1 的 keep() 过滤掉它们，段2 只补 PHASE2_FIELDS，所以它们
    #    在两段式跑法下会永久消失**，而报告照样渲染得出来。8/10 那份之所以有这些内容，
    #    是因为它绕过模板一次性手写的（正是模板头部记的那次事故）。
    #    已加 qa_report「phase 桶必须覆盖模板字段集」防止再犯。
    "bam", "bam_table", "bam_note",
    "dispersion", "dispersion_note",
    "special_readthrough_table", "special_readthrough_note",
    "adanos_scan_note", "recon_prob_note",
    # ── 2026-08-12 从已退役的 PHASE2_FIELDS / PHASE2_PATCH_FIELDS 并进来（两段式取消）──
    "signal_light", "sector_rs_note", "etf_table_note", "positions_moomoo_note",
    "news_today", "strong_sector_setups_permission",
    "watchlist_abc", "setup_conclusion", "playbook_scenarios",
    "key_takeaways", "today_position", "recon_ledger", "generated_at",
    "sector_rs_tables", "etf_table",
    "positions_moomoo_table", "positions_longbridge_table",
    "defensive_basket", "strong_sector_setups_table",
    "stop_proximity_table", "stop_proximity_note",
    "exit_plan_table", "exit_plan_note",
    # premarket_movers / premarket_movers_note 2026-08-12 整块退役（Vic：「我也不看盘前异动选股」），
    # 模板里留空壳、不进本清单——它们不该再出现在报告里。
]

# ②段1建骨架+写判断列，段2只把「盘前」那一列补进去（用patch_premarket_columns机械完成，
#   段2**不要**重写这几张表的判断文字，除非盘前数据真的推翻了段1的判断——那要在报告里明写）
# 🔴 2026-08-12 退役：**两段式取消，盘前数据模块整体下线。**
# Vic：「我觉得盘前数字没什么用，我也不看盘前异动选股，关于盘前的全部删了吧，
#        我打算以后 3-4 点就触发盘前」
# 3-4 点（SGT）在盘前数据可得（16:00）之前 —— 段2 唯一的机械产出就是补盘前列，
# 没有盘前数据，段2 就没有存在理由。**所有字段回到一个桶（PHASE1_FIELDS）。**
# 触发它的实例：2026-08-11 段2 用盘前弱势判「利多出尽」把 OIH 从 4 分降到 C，
# 收盘 XLE +1.25% 是当日最强板块 —— 而「盘前经常是假的」这条规则是我们自己写的。
PHASE2_PATCH_FIELDS = []   # 退役 2026-08-12，留空壳

# 2026-08-12 起只有一个桶。保留 PHASE1_FIELDS 这个名字是为了不改动所有调用点，
# 但它现在的语义是「盘前报告的全部字段」，所以给一个诚实的别名。
ALL_FIELDS = PHASE1_FIELDS

# ③段2才能定稿：需要盘前报价，或必须等到最后统一决策
PHASE2_FIELDS = []         # 退役 2026-08-12，见上方注释；原内容已并入 PHASE1_FIELDS
_RETIRED_PHASE2_FIELDS = [   # 留档：这些字段现在全部在 PHASE1_FIELDS 里
    "signal_light",            # bias 那格原本写盘前动向，现在写隔夜收盘定性
    "sector_rs_note", "etf_table_note", "positions_moomoo_note",
    "premarket_movers", "premarket_movers_note",
    "news_today",              # 段1之后新增的新闻
    "strong_sector_setups_permission",
    # 2026-07-28起A/B/C三级只写 watchlist_abc（旧的三字段会让渲染器抛异常，
    # 体检表再提示它们就会把新会话直接引到坑里）
    "watchlist_abc", "setup_conclusion",
    "playbook_scenarios", "key_takeaways", "today_position", "recon_ledger",
    "generated_at",
    # 🔴 2026-08-11 补（同上那一批漏网字段，但这两个归段2）：止损贴近度表要吃盘前报价
    #    才能判「今晚撤单 / 看盘前动向」，段1 跑出来那一列只会是 "-"。
    "stop_proximity_table", "stop_proximity_note",
    # 2026-08-11 Vic 点名要退出 GLW/MRVL/SOXX/AAOI 后要求「单独拉一张」——
    # 同样吃盘前报价（要判「盘前破没破昨日低/止损」），归段2。
    "exit_plan_table", "exit_plan_note",
]

# 🔴 2026-08-11：三个桶必须**恰好**覆盖 assemble_template.py 的字段集，不多不少。
#    少了 → 段1 keep() 过滤掉、段2 不补回 → 字段永久消失且报告照样渲染（已发生三次）。
#    多了 → QA 会把它报成「自造字段」。
#    这条不写成注释，写成 qa_report 里会失败的检查（见「phase 桶覆盖模板字段集」）。

DRAFT_DIR = ROOT / "data" / "daily"


def _draft_path(day: str):
    """day: 'YYYY-MM-DD'"""
    return DRAFT_DIR / f"{day}-premarket.json"


def save_premarket_draft(day: str, data: dict, phase: int, note: str = "") -> Path:
    """段1/段2统一用这个落盘。phase=1写草稿（不渲染），phase=2写定稿（之后才render）。
    段1写完请在对话里把 `_phase1_note` 的内容也讲给Vic，他白天就能看到隔夜结论。"""
    from datetime import datetime
    data = dict(data)
    data["_phase"] = phase
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M SGT")
    if phase == 1:
        data["_phase1_at"] = stamp
        if note:
            data["_phase1_note"] = note
    else:
        data.setdefault("_phase1_at", data.get("_phase1_at"))
        data["_phase2_at"] = stamp
    p = _draft_path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_premarket_draft(day: str):
    """段2开头调这个。返回 (draft, warnings)。
    draft为None表示段1还没跑——这时不要硬着头皮从零做，先告诉Vic段1缺失。"""
    p = _draft_path(day)
    warns = []
    if not p.exists():
        return None, [f"🔴段1草稿不存在（{p.name}）——白天那一段没跑，或者日期不对"]
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("_phase") == 2:
        warns.append("⚠️这份JSON已经是段2定稿（_phase=2）——今天的盘前已经跑完了，"
                     "确认是要重做还是日期写错了")
    elif d.get("_phase") != 1:
        warns.append("⚠️草稿没有_phase标记，可能是两段式启用前的旧格式，按整份重做处理")
    missing = [f for f in PHASE1_FIELDS if f not in d and f not in ("subtitle", "badges")]
    if missing:
        warns.append(f"⚠️段1应有但缺失的字段：{missing}")
    return d, warns


def patch_premarket_columns(draft: dict, pm: dict) -> list:
    """**退役 2026-08-12**（两段式取消，盘前数据模块整体下线）。

    保留函数体是为了让旧的 scratchpad 脚本不会 ImportError，但它现在什么都不做、
    并且会喊一声——如果哪天有人又调到它，说明有个地方还在按两段式跑。

    原文档：段2把盘前列机械地补进段1建好的表（PHASE2_PATCH_FIELDS）。返回改动说明列表。

    这个函数存在的意义：段1已经把「驱动/原因」「判断」「论点检查」这些判断列写好了，
    段2如果整表重建就会把那些判断冲掉——两段式就退化成"跑两遍"。所以段2只补数据列，
    判断列原样保留；只有当盘前数据真的推翻段1判断时，才手动改那一行并在报告里写明。

    幂等：重复调用不会叠加"（盘前x%）"后缀（靠已含"盘前"字样判断跳过）。
    """
    return ["⚠️ patch_premarket_columns 已于 2026-08-12 退役（盘前数据模块下线），本次未做任何改动"]

    changes = []           # ↓ 以下为退役前的实现，保留作历史记录，不再执行

    def pmp(tk):
        v = (pm.get(tk) or {}).get("pm_pct")
        return ("%+.2f%%" % v) if v is not None else None

    for grp in draft.get("sector_rs_tables") or []:
        n = miss = 0
        for r in grp.get("rows", []):
            # 占位符=任何不含"%"的内容（"-" / "无盘前quote" / 空）；已经是真实百分比的不覆盖。
            # "无quote"是本函数自己写下的终态（该票确实没有盘前报价），跳过它才能真幂等
            if len(r) > 4 and "%" not in str(r[4]) and str(r[4]) != "无quote":
                v = pmp(r[0])
                r[4] = v or "无quote"
                n += 1
                miss += 0 if v else 1
        if n:
            changes.append(f"sector_rs_tables[{grp.get('title','?')[:12]}]: 补了{n}行盘前"
                           + (f"（其中{miss}只无盘前报价）" if miss else ""))

    et = draft.get("etf_table") or {}
    n = 0
    for r in et.get("rows", []):
        if len(r) > 2 and "盘前" not in str(r[2]):
            r[2] = f"{r[2]}（盘前{pmp(r[0]) or '无quote'}）"
            n += 1
    if n:
        changes.append(f"etf_table: 补了{n}行盘前")

    # 2026-08-06 Vic：「持仓2个表格盘前价格直接给一列吧」——原来是塞进「现价」格里加后缀，
    # 一格两个数字很难扫。改成在「现价」后面插一列「盘前」。
    for key in ("positions_moomoo_table", "positions_longbridge_table"):
        tb = draft.get(key) or {}
        rows = tb.get("rows", [])
        hd = tb.get("headers") or []
        hl = tb.get("row_highlights")
        if "盘前" in hd:                      # 幂等：已经插过就不再插
            continue
        n = 0
        if len(hd) > 1:
            tb["headers"] = hd[:2] + ["盘前"] + hd[2:]
            cw = tb.get("col_widths")
            if cw and len(cw) == len(hd):
                tb["col_widths"] = ["8%", "10%", "10%", "9%", "8%", "17%", "16%", "22%"]
            # 新列必须进 num_cols，否则涨跌色不生效（QA第10条会抓）；
            # 原有 num_cols 里 >=2 的下标要整体右移一位
            nc = [i if i < 2 else i + 1 for i in (tb.get("num_cols") or [])]
            tb["num_cols"] = sorted(set(nc + [2]))
        for i, r in enumerate(rows):
            alert = position_pm_alert(pm, r[0])
            cell = (pmp(r[0]) or "-") + ((" " + alert) if alert else "")
            r[:] = r[:2] + [cell] + r[2:]
            if alert and isinstance(hl, list) and i < len(hl):
                hl[i] = "warn"
            n += 1
        if n:
            changes.append(f"{key}: 新增「盘前」列 {n} 行" + ("（含🔴持仓警报）" if any(
                position_pm_alert(pm, r[0]) for r in rows) else ""))

    n = 0
    for d in draft.get("defensive_basket") or []:
        if isinstance(d, dict) and "盘前" not in str(d.get("pct", "")):
            d["pct"] = "盘前" + (pmp(d.get("ticker", "")) or "无quote")
            n += 1
    if n:
        changes.append(f"defensive_basket: 补了{n}只盘前%")

    return changes


def premarket_phase_status(day: str, ds: str = None) -> dict:
    """两段式的体检表：今天跑到哪一步了、段2还缺什么。
    每天段2会话的第一件事就是看这个（`python scripts/premarket_status.py`）。"""
    from datetime import date as _date
    ds = ds or day.replace("-", "")
    cache_p = ROOT / "data" / "cache" / f"market_{ds}.json"
    st = {"day": day, "cache_exists": cache_p.exists(), "cache_data_date": None,
          "setups_exists": (ROOT / "data" / "cache" / f"setups_{ds}.json").exists(),
          "xscan_exists": (ROOT / "data" / "cache" / f"x_scan_{ds}.json").exists(),
          "earnings_exists": (ROOT / "data" / "cache" / f"earnings_calendar_{ds}.json").exists(),
          "semis_exists": (ROOT / "data" / "cache" / f"semis_scan_{ds}.json").exists(),
          "snap_exists": (ROOT / "data" / "cache" / f"premarket_{ds}.json").exists(),
          "draft_phase": None, "phase2_missing": [], "snap_stale": None, "problems": []}
    if cache_p.exists():
        st["cache_data_date"] = json.loads(cache_p.read_text(encoding="utf-8")).get("data_date")
    p = _draft_path(day)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        st["draft_phase"] = d.get("_phase")
        st["phase1_at"] = d.get("_phase1_at")
        st["phase2_missing"] = [f for f in PHASE2_FIELDS if f not in d]
        st["patch_pending"] = [f for f in PHASE2_PATCH_FIELDS if f in d
                               and "盘前" not in json.dumps(d[f], ensure_ascii=False)]
    snap = load_premarket_snap(ds)
    if snap:
        vals = [v for v in snap.values() if isinstance(v, dict)]
        stale = [k for k, v in snap.items() if isinstance(v, dict) and v.get("pm_stale")]
        st["snap_stale"] = f"{len(stale)}/{len(vals)} 只标记pm_stale"
        if vals and len(stale) > len(vals) * 0.5:
            st["problems"].append("🔴过半标的pm_stale——盘前报价是上一时段的残留，"
                                  "现在跑段2会把涨跌算反（2026-07-11踩过）。等到SGT 16:00后重跑snap_premarket.py")
    if st["cache_data_date"] == day:
        st["problems"].append("🔴cache的data_date等于报告日本身——说明fetch跑在美股收盘之前，"
                              "拿到的不是完整收盘数据")
    return st


# ---------------- Follow-Through Day（2026-07-31建，Vic带来的O'Neil框架） ----------------
FTD_STATE = ROOT / "data" / "ftd_state.json"
FTD_MIN_GAIN = 1.25      # O'Neil原始门槛
FTD_STRONG_GAIN = 1.70   # MarketSmith对纳指常用的更严门槛，达到记「强FTD」

# 🔴 2026-08-05 改：面板从 QQQ/VOO 两只扩到六只，判定从「任一达标」改成「同日≥2只达标」。
# 起因是 Vic 的质疑：「单看 smh 和 qqq 是用 ftd，但是结合标普和 iwm 道指和个股，结论就会不同了」。
# 根因：QQQ/VOO 都是市值加权，成交量被少数大票的换手掩盖（8/3 QQQE 量1.65× 全场最高＝真实
# 买盘在中小票上，而 QQQ 只有 0.89×）；且 O'Neil 原版用的是 Nasdaq **Composite**(3000+只)，
# 拿 QQQ(100只市值加权)代理本身就有偏差。
# 🔴回测口径的一个坑，务必连着读（2026-08-05 当天就踩到并修正）：
# 首版回测没套 O'Neil 的 Day 4-7 窗口（只查"D0后10日内首个达标日"），那个口径下
# 「六只≥2」看起来三个时间窗全面最优（触发17/24、+20日94%/+3.50%）。**但套上窗口后，
# 「六只≥2」的触发率从 17/24 崩到 6/24、样本 n=5，那组漂亮数字直接不成立。**
# 套窗口后的真实对照（与本函数实装口径一致，24次rally attempt）：
#   QQQ/VOO任一   触发11/24  +10日胜率60%/+0.84%  +20日90%/+3.25%
#   **六只任一**  触发13/24  +10日胜率67%/+1.07%  +20日83%/+2.89%  ← 采用
#   六只≥2        触发 6/24  n=5，统计上无意义
# 采用「六只任一」的理由：触发率比现行高（13 vs 11，少漏机会）、+10日更好，
# +20日的 83% vs 90% 差的是1-2次事件（n=12 vs n=10）属噪音范围；且只动面板一个参数，
# 不动窗口和确认数，过拟合风险最小。**教训：回测口径必须跟实装口径逐条对齐再下结论。**
FTD_PANEL = ["QQQ", "VOO", "IWM", "DIA", "RSP", "QQQE"]
FTD_MIN_CONFIRM = 1      # 同一交易日至少几只面板成员达标才算FTD（改2需先重跑带窗口的回测）


def _ftd_state() -> dict:
    if FTD_STATE.exists():
        return json.loads(FTD_STATE.read_text(encoding="utf-8"))
    return {}


def set_ftd_day1(date_str: str, lows: dict, note: str = "") -> None:
    """由Vic肉眼确认Day 1后调用（**不自动判定Day 1**，这是他的原话要求：
    「第一天我肉眼看，只有在出现第一根绿bar以后，你才开始观测follow through」）。
    lows = {"QQQ": 673.30, "VOO": 675.21}，是Day 1当天的最低价，作为count重置线。"""
    st = _ftd_state()
    st.update({"day1_date": date_str, "day1_lows": lows,
               "confirmed_by": note or "Vic肉眼", "indices": list(lows)})
    FTD_STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def ftd_status(ctx=None) -> dict:
    """Follow-Through Day 追踪（O'Neil / MarketSmith 规则，2026-07-31 Vic带入框架）。

    规则（按Vic提供的原文实现）：
      · Day 1 = 修正后第一根收阳的bar，**由Vic肉眼确认**，不自动判定
      · Days 2-3 不必上涨，只要 Day 1 的最低价不被跌破，rally attempt 就还活着
      · Day 4-7 内，任一主要指数（S&P500 / 纳指）单日涨幅 ≥1.25% 且 **成交量高于前一日**
        → 该日即 Follow-Through Day，下降趋势确认结束
      · **跌破 Day 1 最低价 → 计数重置**（需要新的 Day 1）
      · Day 10 之后才出现的 FTD 成功率明显偏低，标注但不否决

    返回 {day1, day_n, reset, window, rows[], verdict, note}。
    rows 每项 = {ticker, day_n, pct, vol_ratio_prev, low, undercut, pass_gain, pass_vol, is_ftd}
    """
    st = _ftd_state()
    # 🔴 2026-08-06 Vic 暂停 FTD 追踪（见 CONTEXT.md「FTD 暂停」节）。
    # 不删代码、不删历史，只停止每日追踪——他要先想清楚换哪套理论（倾向 Deemer）。
    # 重启方式：把 data/ftd_state.json 的 parked 改回 false，并重新肉眼确认 Day 1。
    if st.get("parked"):
        return {"verdict": "**FTD 追踪已暂停**（%s，Vic 决定）" % st.get("parked_at", ""),
                "rows": [], "parked": True, "day1": st.get("day1_date"),
                "reset_lines": st.get("day1_lows", {}),
                "note": st.get("parked_reason", "")}
    if not st.get("day1_date"):
        return {"verdict": "未设定Day 1", "rows": []}
    from longport.openapi import QuoteContext, Config, Period, AdjustType
    ctx = ctx or QuoteContext(Config.from_apikey_env())
    d1 = st["day1_date"]
    lows = st.get("day1_lows", {})
    panel = st.get("indices") or FTD_PANEL
    # 2026-08-05：面板扩到六只后，state 里只存了 QQQ/VOO 的 Day1 低点，
    # 缺的用该票自己 Day 1 当天的最低价补（等价，只是没被人工确认过）
    seqs, day_n, reset = {}, 0, False
    for tk in panel:
        bars = [{"date": str(b.timestamp.date()), "c": float(b.close),
                 "l": float(b.low), "v": b.volume}
                for b in ctx.candlesticks(f"{tk}.US", Period.Day, 40, AdjustType.NoAdjust)]
        idx = next((i for i, b in enumerate(bars) if b["date"] >= d1), None)
        if idx is None or idx == 0:
            continue
        seq = bars[idx:]
        seqs[tk] = {"seq": seq, "prev0": bars[idx - 1], "low": lows.get(tk, seq[0]["l"])}
        day_n = max(day_n, len(seq))

    # 逐日算每只票的达标情况（不再只看最后一根），这样窗口内早几天成立的FTD也能被追认
    daily = {}          # date -> {ticker: (pct, vr, pass)}
    for tk, o in seqs.items():
        seq, prev = o["seq"], o["prev0"]
        for i, b in enumerate(seq):
            p = seq[i - 1] if i else prev
            pct = (b["c"] / p["c"] - 1) * 100
            vr = (b["v"] / p["v"]) if p["v"] else None
            ok = pct >= FTD_MIN_GAIN and vr is not None and vr > 1.0
            daily.setdefault(b["date"], {})[tk] = {"pct": pct, "vr": vr, "pass": ok,
                                                   "n": i + 1}
        # 🔴计数重置只认**Vic人工确认过Day1低点的那几只**（day1_lows 里有的）。
        # 2026-08-05 面板扩到六只后，其余四只的Day1低点是自动填的，用它们触发重置等于
        # 把「任一指数破位就重来」的门槛拉到六倍严——实测 IWM 7/31 只破自己Day1低 0.39%
        # 就会把整个 rally attempt 判死，而 QQQ/VOO 当时离重置线还有 +1% 以上。
        if tk in lows and any(b["l"] < o["low"] for b in seq[1:]):
            reset = True

    ftd_date, ftd_members = None, []
    for d in sorted(daily):
        hits = [t for t, v in daily[d].items() if v["pass"] and 4 <= v["n"] <= 7]
        if len(hits) >= FTD_MIN_CONFIRM and not reset:
            ftd_date, ftd_members = d, hits
            break

    rows = []
    for tk, o in seqs.items():
        seq = o["seq"]
        last_d = seq[-1]["date"]
        v = daily[last_d][tk]
        n = v["n"]
        under = [b["date"] for b in seq[1:] if b["l"] < o["low"]]
        rows.append({"ticker": tk, "day_n": n, "pct": round(v["pct"], 2),
                     "vol_ratio_prev": round(v["vr"], 2) if v["vr"] is not None else None,
                     "day1_low": o["low"], "undercut": bool(under),
                     "undercut_dates": under,
                     "pass_gain": v["pct"] >= FTD_MIN_GAIN,
                     "pass_vol": v["vr"] is not None and v["vr"] > 1.0,
                     "in_window": 4 <= n <= 7, "is_ftd": tk in ftd_members,
                     "strong": v["pct"] >= FTD_STRONG_GAIN})
    rows.sort(key=lambda r: FTD_PANEL.index(r["ticker"]) if r["ticker"] in FTD_PANEL else 99)

    if reset:
        verdict = "计数重置——Day 1 最低价被跌破，需要重新肉眼确认新的 Day 1"
    elif ftd_date:
        verdict = (f"**Follow-Through Day 成立（{ftd_date}，"
                   f"{len(ftd_members)}/{len(seqs)}只同日达标：{'/'.join(ftd_members)}）**")
    elif day_n < 4:
        verdict = f"Rally Attempt Day {day_n}——**还没进 FTD 观察窗（Day 4-7）**"
    elif day_n <= 7:
        verdict = f"Day {day_n}，在观察窗内但今日不合格"
    elif day_n <= 10:
        verdict = f"Day {day_n}，已过 Day 7 —— 仍可能出现但已偏晚"
    else:
        verdict = f"Day {day_n}，已过 Day 10 —— **此后出现的 FTD 成功率明显偏低**"
    return {"day1": d1, "day_n": day_n, "reset": reset, "verdict": verdict,
            "rows": rows, "confirmed_by": st.get("confirmed_by", ""),
            "ftd_date": ftd_date, "ftd_members": ftd_members,
            "panel": list(seqs), "min_confirm": FTD_MIN_CONFIRM}


def ftd_table(status: dict) -> dict:
    """把 ftd_status() 渲成报告表。"""
    rows = []
    for r in status.get("rows", []):
        chk = lambda ok: "✓" if ok else "✗"
        # 🔴量的读法跟着 Day 计数走（2026-08-05）：Day 2-3 还在 rally attempt 里，
        # 缩量=卖压枯竭是加分；Day 4-7 是确认日，缩量=无需求是减分。
        vctx = "attempt" if r["day_n"] <= 3 else "breakout"
        rows.append([r["ticker"], f"Day {r['day_n']}",
                     ("%+.2f%%" % r["pct"]) if r["pct"] is not None else "-",
                     volume_read(vctx, r["vol_ratio_prev"])[1],
                     "%.2f" % r["day1_low"],
                     ("**已跌破**" if r["undercut"] else "未破"),
                     ("**达标（计入FTD）**" if r["is_ftd"] else
                      ("窗口内不合格" if r["in_window"] else "未进窗口(Day 4-7)"))])
    n_hit = len(status.get("ftd_members") or [])
    n_panel = len(status.get("panel") or []) or len(rows)
    if status.get("ftd_date"):
        foot = "**FTD 成立：%s，%d/%d 只同日达标**" % (status["ftd_date"], n_hit, n_panel)
    else:
        foot = ("尚未成立：需要同一交易日**至少 %d 只**面板成员同时满足"
                "「涨幅 ≥1.25%% 且成交量高于前一日」" % status.get("min_confirm", FTD_MIN_CONFIRM))
    return {"headers": ["指数", "计数", "当日涨幅", "量/前日", "Day1低点", "重置线", "判定"],
            "rows": rows, "num_cols": [2], "center_cols": [1, 5, 6],
            "table_class": "fixed-cols", "footnote": foot,
            "col_widths": ["10%", "10%", "13%", "12%", "13%", "14%", "28%"]}


# ---------------- 反弹品类入场（2026-07-31建） ----------------
# 起因：Vic 2026-07-31 —「跌了不买，涨了又说太多，不买」。复盘属实——7/28~7/31 四天只给出
# 1 个A级候选。根因不是保守，是**框架里只有一种买法**：Setup A/B/C/D/E 全部是「上升趋势中的
# 回踩/突破」，在下跌和反弹初期这类形态天然极少，所以系统性地产不出信号。
#
# 实测（n=22，深跌后单日≥+8%大阳，近250日）：
#   · 3日内回踩9EMA的占 91%  → 「等回踩」不是空话，等得到
#   · 但回踩组3日后平均 -0.2%，个案 -22.7%~+29.2%  → 等到了也没有edge
#   → 结论：**问题不在等不等回踩，在于这类形态单独看3日期望值≈0**。
#     真正提供edge的是市场级确认（FTD），所以反弹品类必须挂在FTD上，而不是单看个股。
#
# O'Neil原文对FTD日的指令是 **buy starter positions**（买入指令，不是等待指令），
# 这里照此实现：FTD成立当天按1/3仓建starter，不等回踩；错了也只是小额暴露。
BOUNCE_MIN_ADR = 6.0          # 动量交易的最低振幅要求（Vic：ADR太低的不做）
BOUNCE_MIN_DRAWDOWN = -15.0   # 距25日高，确认是"深跌后的反弹"而非追高
BOUNCE_STARTER_FRAC = "1/3"   # starter仓位比例
BOUNCE_MAX_TOTAL_FRAC = "1/3" # 反弹品类合计仓位上限


def adr_pct(bars: list, n: int = 20) -> float:
    """ADR% = 近n日 (High/Low - 1) 的均值。动量交易的核心筛选指标。"""
    seg = bars[-n:]
    if not seg:
        return 0.0
    return sum((b["h"] / b["l"] - 1) * 100 for b in seg if b.get("l")) / len(seg)


def bounce_candidates(tickers: list, ftd_ok: bool, ctx=None, asof: str = None) -> list:
    """反弹品类候选（与Setup A并列的**第二种买法**，不是替代）。

    门槛：ADR ≥6%（够动量交易） + 距25日高 ≤-15%（确实是深跌） + 已收复9EMA。
    入场：**FTD成立当天不等回踩，收盘建1/3 starter仓**；FTD未成立则只列观察。
    失效：跌回9EMA下方且不收回。
    上限：本品类合计不超过总仓位 1/3。

    返回 [{ticker, adr, dd25, dist_ema9, range_pos, eligible, action}]，按ADR降序。
    """
    from longport.openapi import QuoteContext, Config, Period, AdjustType
    ctx = ctx or QuoteContext(Config.from_apikey_env())
    out = []
    for t in tickers:
        try:
            raw = ctx.candlesticks(f"{t}.US", Period.Day, 60, AdjustType.NoAdjust)
        except Exception:
            continue
        bars = [{"d": str(b.timestamp.date()), "h": float(b.high),
                 "l": float(b.low), "c": float(b.close)} for b in raw]
        if asof:
            bars = [b for b in bars if b["d"] <= asof]
        if len(bars) < 30:
            continue
        cl = [b["c"] for b in bars]
        k = 2.0 / 10
        e9 = cl[-30]
        for x in cl[-29:]:
            e9 = x * k + e9 * (1 - k)
        adr = adr_pct(bars)
        dd25 = (cl[-1] / max(cl[-26:-1]) - 1) * 100
        d9 = (cl[-1] / e9 - 1) * 100
        hi, lo = bars[-1]["h"], bars[-1]["l"]
        rp = round((cl[-1] - lo) / (hi - lo) * 100) if hi > lo else None
        ok = adr >= BOUNCE_MIN_ADR and dd25 <= BOUNCE_MIN_DRAWDOWN and d9 > 0
        out.append({"ticker": t, "adr": round(adr, 1), "dd25": round(dd25, 1),
                    "dist_ema9": round(d9, 2), "range_pos": rp, "ema9": round(e9, 2),
                    "eligible": ok,
                    "action": (f"**FTD已成立 → 收盘建{BOUNCE_STARTER_FRAC}仓，不等回踩**"
                               if (ok and ftd_ok) else
                               "合格，等FTD触发" if ok else
                               ("ADR不足" if adr < BOUNCE_MIN_ADR else
                                "未收复9EMA" if d9 <= 0 else "跌幅不够深"))})
    return sorted(out, key=lambda x: -x["adr"])


def position_governance(positions: list = None) -> dict:
    """持仓治理检查（2026-08-01 Vic批准启用为硬性规则）。

    起因：「每笔仓位都有持有理由」连续两周未做到——W31盘点13笔持仓里
    **4笔thesis是「待Vic补录」、2笔止损为空**。按CONTEXT「同一缺口连续两周→
    升级为硬性规则」，从本周起：**thesis为空或止损为空的仓位，盘后报告标红单列一节**，
    不再只在持仓表备注里提一句。

    返回 {"rows": [...], "n_bad": int}，rows 直接喂 build_table。
    """
    positions = positions if positions is not None else load_tradebook_positions()
    PLACEHOLDER = ("待vic补录", "待补录", "待填", "tbd", "-", "")
    rows = []
    for p in positions:
        th = str(p.get("thesis") or "").strip()
        stop = p.get("stop")
        bad_th = (not th) or th.lower().replace(" ", "") in PLACEHOLDER
        bad_stop = stop in (None, "", 0)
        if not (bad_th or bad_stop):
            continue
        miss = []
        if bad_th:
            miss.append("**持有理由**")
        if bad_stop:
            miss.append("**止损**")
        rows.append([p.get("ticker", "-"), p.get("account", "-"), str(p.get("qty", "-")),
                     ("%.2f" % p["cost"]) if p.get("cost") else "-",
                     ("%.2f" % stop) if stop else "**空**",
                     (th[:22] if th else "**空**"),
                     "缺 " + " + ".join(miss)])
    return {"rows": rows, "n_bad": len(rows)}


def position_governance_table(gov: dict) -> dict:
    return {"headers": ["TICKER", "账户", "股数", "成本", "止损", "持有理由", "缺什么"],
            "rows": gov.get("rows", []), "num_cols": [], "center_cols": [1, 2],
            "table_class": "fixed-cols",
            "col_widths": ["11%", "13%", "9%", "11%", "12%", "26%", "18%"]}


# =========================================================================
# 撤单清单 stop_proximity（2026-08-07 建，源自 Vic 当天的原话：
# 「实际很难，因为我有时候持仓很多，也许应该只撤那些接近止损的」）
#
# 背景：执行纪律 #8 说的是「盘前不留挂单，开盘后等 5-15 分钟再决定」。
# 8/6 是它没被执行的一天（GTLB 收盘区间 92%、VEEV 98%，两笔都是先破止损后收回）。
# Vic 指出的问题不是规则错，是**规则的粒度错**——十几笔持仓全部撤单不现实。
#
# 所以把「撤哪些」变成一个每天自动算的清单，判据是**距止损还有几个 ATR**，
# 不是绝对百分比：ATR 才是「一根正常日内波动能走多远」的度量。
#   · < 0.7 ATR  → 今晚必撤（开盘那一段的正常波动就能打到）
#   · 0.7-1.0 ATR → 看盘前动向决定（盘前若已下跌则一并撤）
#   · > 1.0 ATR  → 挂单照留，不动
# 阈值是初版，攒够样本再回测——先当工具用，不当规则。
STOP_PULL_HARD = 0.7
STOP_PULL_SOFT = 1.0


def stop_proximity_rows(cache: dict, positions: list = None, pm_cache: dict = None) -> dict:
    """返回 {"rows", "n_hard", "n_soft", "n_keep", "n_nostop"}，rows 直接喂 build_table。

    距止损/ATR = (现价 - 止损) / ATR14。
    2026-08-07 Vic：「留着的别写了，好长的报告」——**只列需要动作的行**（<1.0ATR）。
    「挂单照留」和「无止损无单可撤」的不进表，只在返回值里计数、由 note 一句带过。
    """
    positions = positions if positions is not None else load_tradebook_positions()
    metrics = cache.get("metrics", {})
    rows, n_hard, n_soft, n_keep, n_nostop = [], 0, 0, 0, 0
    for p in sorted(positions, key=lambda x: str(x.get("ticker"))):
        tk = p.get("ticker")
        m = metrics.get(tk) or {}
        px, atr = m.get("close"), m.get("atr14")
        stop = p.get("stop")
        pm_pct = ((pm_cache or {}).get(tk) or {}).get("pm_pct")
        pm_cell = ("%+.2f%%" % pm_pct) if pm_pct is not None else "-"
        if not stop:
            n_nostop += 1           # 无单可撤；「没止损」这件事由仓位治理表负责，不在这里重复
            continue
        if not px or not atr:
            rows.append([tk, p.get("account", "-"), "-", "%.2f" % stop, "-", "-", pm_cell, "缺现价/ATR，人工确认"])
            continue
        dist_pct = (px - stop) / px * 100
        dist_atr = (px - stop) / atr
        if dist_atr < STOP_PULL_HARD:
            verdict, n_hard = "**今晚撤单**", n_hard + 1
        elif dist_atr < STOP_PULL_SOFT:
            verdict, n_soft = "看盘前动向", n_soft + 1
        else:
            n_keep += 1
            continue
        rows.append([tk, p.get("account", "-"), "%.2f" % px, "%.2f" % stop,
                     "%+.2f%%" % dist_pct, "%.2f" % dist_atr, pm_cell, verdict])
    return {"rows": rows, "n_hard": n_hard, "n_soft": n_soft,
            "n_keep": n_keep, "n_nostop": n_nostop}


def stop_proximity_table(sp: dict) -> dict:
    return {"headers": ["TICKER", "账户", "现价", "止损", "距止损%", "距止损/ATR", "盘前", "今晚处理"],
            "rows": sp.get("rows", []), "num_cols": [4, 5, 6], "center_cols": [1, 7],
            "table_class": "fixed-cols",
            "col_widths": ["9%", "11%", "10%", "10%", "11%", "12%", "9%", "28%"]}


# =========================================================================
# 今日退出执行表 exit_plan（2026-08-11 建，Vic：「我想盘前止损 glw mrvl soxx aaoi 这几个」
# → 「单独拉一张」）
#
# 跟上面的撤单清单 stop_proximity 不是一回事，**别合并**：
#   · stop_proximity 回答「今晚哪几张挂单要撤」——全仓扫描，按距止损/ATR 自动入选
#   · exit_plan     回答「我已经决定要出的这几笔，今晚怎么出」——**Vic 点名，我不代选**
#
# 🔴 这张表的核心作用是把「盘前挂单」翻译成执行纪律 #8 的动作序列。
# #8（2026-07-08 BRKR 那笔沉淀的）：盘前盘后不留止损单，薄流动性专门洗单；
# **撤掉 ORDER 不等于撤掉 LEVEL** —— SOP = 开盘后等 5-15 分钟，30 分钟内没收回就无条件出。
# 所以「观察位」按三种情况给，不是一个数：
#   · 盘前价已破止损 → 观察位 = **止损价**（#8 原文场景）
#   · 昨天收在区间 ≤20%（收盘就在当日最低区）→ 观察位 = **昨日中点（收回位）**
#     🔴 这一档是 2026-08-11 首日试跑当场发现的：GLW / SOXX / MRVL 昨天全收在区间 0–1%，
#     **昨日低点几乎等于收盘价**（SOXX 低点 529.39 = 收盘价），拿它当观察位等于零缓冲、
#     任何一个红 tick 都算「破位延续」。而且问法本身就错了——**收在最低意味着破位已经发生**，
#     该问的不是「会不会破」而是「能不能收回来」。所以这一档给收回位，方向反过来。
#   · 其余（昨天收在区间 >20%）→ 观察位 = **昨日低点**（破了才叫延续，没破就是噪音）
EXIT_LOW_CLOSE_RANGE = 20      # 收盘区间 ≤ 这个百分位 = 破位已确认，改看收回位
#
# 🔴 判定列只描述价格在哪一侧，**不写「该卖/该留」** —— 出不出是 Vic 已经决定的事，
#    这张表只负责让他执行得准。Claude 不代下单、不代记录。
# 🔴 v4（2026-08-11 当天第三次改，Vic：「但是如果一直向下的话，我会恐慌止损吧。。」）
# 前三版都给「价格观察位」，Vic 一句话点破根本问题：**任何价格条件都会在开盘那一刻
# 把「要不要出」这个已经做完的决定重新打开一次**，而那正是他最容易恐慌的时刻。
# 而且我把纪律 #8 用错了场景——#8 的锚点是**前一晚就定死的止损位**，那 5-15 分钟只是
# 躲开盘噪音；我却把锚点换成「开盘 15 分钟自己走出来的区间」= 盘中才成形的数。
# **前一晚定死的数不会被恐慌移动，盘中形成的数会。**
# 支持这个改法的自有数据：0 天持有胜率 8%／平均 -2.82%（所有分桶最差）、
# 有卖在当日区间最低 15% 的记录（DUOL/TTAN）、机械跟单 R:R 1.00 vs 自主 0.12。
# **所以 v4 用时间条件，不用价格条件**：分批定时出，唯一的价格条件是早就写下的止损。
EXIT_PLAN_HEADERS = ["TICKER", "账户/股数", "成本", "昨收（盘前）", "自成本",
                     "止损（不改）", "分批计划", "备注"]


def exit_plan_rows(cache: dict, tickers, positions: list = None,
                   pm_cache: dict = None, reasons: dict = None) -> dict:
    """Vic 点名要退出的标的 → 可执行的退出表。

    tickers 可以是 ["GLW", ...]，也可以是 [("MRVL","longbridge"), ...] 精确到账户
    （同一只票在两个账户各有一笔时必须指定，否则两笔都出——MRVL 2026-08-11 就是这个情况）。
    reasons: {ticker 或 (ticker,account): "退出理由"}，写进 note 不占列。
    """
    positions = positions if positions is not None else load_tradebook_positions()
    metrics = cache.get("metrics", {})
    want = []
    for t in tickers:
        want.append(t if isinstance(t, (tuple, list)) else (t, None))

    rows, warnings = [], []
    for tk, acct in want:
        lots = [p for p in positions if p.get("ticker") == tk
                and (acct is None or p.get("account") == acct)]
        if not lots:
            warnings.append("%s%s 在 tradebook 里找不到持仓" % (tk, "/" + acct if acct else ""))
            continue
        if acct is None and len(lots) > 1:
            warnings.append("🔴**%s 在 %d 个账户各有一笔**（%s）——没指定账户，两笔都列出来了，"
                            "下单前确认你要出的是哪一笔"
                            % (tk, len(lots), " / ".join(p.get("account", "?") for p in lots)))
        for p in lots:
            m = metrics.get(tk) or {}
            px, t1 = m.get("close"), m.get("t1_pct")
            low_pct, high_pct, rp = m.get("low_pct"), m.get("high_pct"), m.get("range_pos")
            cost, stop = p.get("cost"), p.get("stop")
            pm_pct = ((pm_cache or {}).get(tk) or {}).get("pm_pct")
            # 昨日高低点：low_pct/high_pct 是相对前收的百分比，先还原前收
            prev_close = (px / (1 + t1 / 100)) if (px and t1 is not None) else None
            day_low = (prev_close * (1 + low_pct / 100)) if (prev_close and low_pct is not None) else None
            day_high = (prev_close * (1 + high_pct / 100)) if (prev_close and high_pct is not None) else None
            day_mid = ((day_high + day_low) / 2) if (day_high and day_low) else None
            pm_px = (px * (1 + pm_pct / 100)) if (px and pm_pct is not None) else None

            close_cell = "%.2f" % px if px else "-"
            close_cell += "（%s）" % (("%+.2f%%" % pm_pct) if pm_pct is not None else "无盘前quote")
            pl = ("%+.2f%%" % ((px / cost - 1) * 100)) if (px and cost) else "-"
            if stop and px:
                stop_cell = "%.2f / %+.2f%%" % (stop, (px / stop - 1) * 100)
            else:
                stop_cell = "**无止损**"

            # v4：分批计划（时间条件）+ 备注（价格只作参照）
            plan = ("1/2 市价 @22:30–23:00 SGT<br>1/2 挂 **MOC**（收盘价成交）"
                    if (p.get("qty") or 0) >= 10 else "**一次性** @22:30–23:00 SGT<br>（不足 10 股不拆）")
            if pm_pct is not None and stop and pm_px is not None and pm_px < stop:
                memo = ("🔴**盘前已跌破止损 %.2f** —— 不用等时点，"
                        "按纪律#8：开盘后 5–15 分钟内没收回就整笔出" % stop)
            elif pm_pct is not None and pm_pct > 0:
                memo = ("**盘前 %+.2f%%，比昨收好** —— 这是更好的出场价，"
                        "**不是重新考虑的理由**（要不要出昨晚已决定）" % pm_pct)
            elif pm_pct is not None:
                memo = "盘前 %+.2f%%，按计划执行" % pm_pct
            else:
                memo = "无盘前 quote，按计划执行"
            rows.append([tk, "%s / %s股" % (p.get("account", "-"), p.get("qty", "-")),
                         "%.2f" % cost if cost else "-", close_cell, pl,
                         stop_cell, plan, memo])
            continue

    return {"rows": rows, "warnings": warnings,
            "reasons": reasons or {}, "n": len(rows)}


def exit_plan_table(ep: dict) -> dict:
    return {"headers": EXIT_PLAN_HEADERS, "rows": ep.get("rows", []),
            "num_cols": [4], "center_cols": [1],
            "table_class": "fixed-cols",
            "col_widths": ["8%", "12%", "8%", "13%", "8%", "12%", "13%", "26%"]}


# =========================================================================
# 离散度 dispersion（2026-08-05 建，源自 Vic 老师：「ftd 20年前的东西，如今要有 situation awareness」）
#
# 把那句话翻成可测命题：**FTD／闸门是市场级的二元信号；当板块离散度高时，
# 指数信号能解释的 P&L 比例下降**。所以需要一个每日读数来决定
# 「今天该更信指数信号，还是更信选股」。
#
# 两个口径，含义不同、不要混：
#  · **已实现离散度**（realized cross-sectional dispersion）= 11个XL板块当日收益的横截面标准差。
#    回看型，可以立刻回填一年历史算分位。
#  · **隐含相关性**（Cboe Implied Correlation，COR1M/COR3M，Vic 2026-08-05 加进宏观Sheet）。
#    前瞻型，**越低=市场预期未来离散度越高**。我们没有它的历史，只能从 2026-08-05 起自己攒。
#
# 关键比值 `ratio = 离散度 ÷ |指数当日涨跌|`：指数动一格、板块之间散多少。
# 比值越高，指数信号越没信息量。实测（2026-08-05，258个交易日）：全样本中位数 1.63、
# 最近1个月 1.96（1.20倍）；而 7/24、7/27 那种指数几乎不动的日子能到 11~22。
DISP_SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB", "XLC"]
DISP_HISTORY = ROOT / "data" / "dispersion_history.json"


def dispersion_series(ctx=None, days: int = 260, asof: str = None):
    """算 [(日期, 板块横截面标准差, |指数涨跌|, 比值)]，最新在后。asof 给定则只算到该日（含）。"""
    import statistics
    from longport.openapi import QuoteContext, Config, Period, AdjustType
    ctx = ctx or QuoteContext(Config.from_apikey_env())
    bars = {}
    for t in DISP_SECTORS + ["VOO"]:
        bars[t] = [{"d": str(b.timestamp)[:10], "c": float(b.close)}
                   for b in ctx.candlesticks(f"{t}.US", Period.Day, days, AdjustType.NoAdjust)]
    idx = {t: {b["d"]: i for i, b in enumerate(bars[t])} for t in bars}

    def ret(t, d):
        i = idx[t].get(d)
        return None if (i is None or i == 0) else (bars[t][i]["c"] / bars[t][i - 1]["c"] - 1) * 100

    out = []
    for d in [b["d"] for b in bars["VOO"]][1:]:
        if asof and d > asof:
            continue
        r = [x for x in (ret(t, d) for t in DISP_SECTORS) if x is not None]
        v = ret("VOO", d)
        if len(r) < 9 or v is None:
            continue
        sd = statistics.pstdev(r)
        out.append((d, round(sd, 3), round(abs(v), 3), round(sd / max(abs(v), 0.05), 2)))
    return out


def dispersion_reading(cache: dict = None, ctx=None, asof: str = None) -> dict:
    """当日离散度读数 + 一年分位 + 隐含相关性；顺便把当日写进 dispersion_history.json。

    返回 {date, sd, idx_move, ratio, sd_pctile, ratio_pctile, cor1m, cor3m, regime, action}
    regime/action 的分档（2026-08-05 定，**阈值是初版、样本攒厚后要回测**）：
      ratio <1.5  指数主导 → 闸门/FTD 权重高，可按市场级信号行动
      1.5~3.0     混合     → 市场级信号可用，但仓位大小交给选股层决定
      >3.0        选股主导 → 指数信号基本无信息量，当天不做基于大盘判断的仓位动作
    """
    import statistics, json as _json
    ser = dispersion_series(ctx=ctx, asof=asof)
    if not ser:
        return {"error": "无数据"}
    d, sd, mv, ratio = ser[-1]
    sds = sorted(x[1] for x in ser)
    rts = sorted(x[3] for x in ser)
    pct = lambda arr, v: round(sum(1 for x in arr if x <= v) / len(arr) * 100)
    ms = (cache or {}).get("macro_sheet") or {}
    cor1, cor3 = ms.get("COR1M"), ms.get("COR3M")
    if ratio < 1.5:
        regime, action = "指数主导", "闸门/FTD 权重高，可按市场级信号行动"
    elif ratio <= 3.0:
        regime, action = "混合", "市场级信号可用，但仓位大小交给选股层决定"
    else:
        regime, action = "选股主导", "指数信号基本无信息量——当天不做基于大盘判断的仓位动作，只做个股结构"
    rec = {"date": d, "sd": sd, "idx_move": mv, "ratio": ratio,
           "sd_pctile": pct(sds, sd), "ratio_pctile": pct(rts, ratio),
           "cor1m": cor1, "cor3m": cor3, "regime": regime, "action": action,
           "sd_median_1y": round(statistics.median(sds), 3),
           "ratio_median_1y": round(statistics.median(rts), 2)}
    try:
        hist = _json.loads(DISP_HISTORY.read_text(encoding="utf-8")) if DISP_HISTORY.exists() else []
        hist = [h for h in hist if h.get("date") != d] + [rec]
        hist.sort(key=lambda h: h["date"])
        DISP_HISTORY.write_text(_json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    return rec


# =========================================================================
# 🔴 论点退出：代理/杠杆型仓位跟母体的相对强弱（2026-08-06 Vic 定）
#
# 起因 WGMI：Vic 想提前退出，理由是「跑输币价」，但他等的是 200MA（价格信号），
# 而退出理由是相对强弱（另一把尺子）——**用错尺子导致拖延**，浮亏从 -4% 拖到 -7.3%。
# 而当时价格根本没触发止损（-7.3% 只有 0.87×ADR，连一个日常波动都没走完）。
#
# **两把尺子不能互相替代：**
#   · **止损** = 价格线，按 ADR 定（1.5~2×ADR）。LABU 的前低 212.56 ≈ 1.94×ADR，是合理宽度。
#     高波动标的必须给宽止损，否则会被噪音打掉。
#   · **论点退出** = 相对强弱线，跟该仓位的**驱动因子（母体）**比。
#     凡是「某个东西的代理/杠杆」型仓位，论点就是「它应该跟上母体」，
#     跑输母体 = 论点在退化，跟绝对价格无关。
#
# **触发条件（初版，样本攒厚后回测）：比值连续 3 天低于其 20 日均值 → 论点退出。**
# 配合已有的 peel 规则（KRE 2026-07-30）：论点退出触发但价格结构没坏时，先出一半。
#
# 母体映射由 Vic 指定，不要自己猜——猜错了整条判断就是错的。
# 🔴 建成当天就发现必须分两类（2026-08-06，跑完数据才看出来）：
#
#  ①**代理型**：跟母体是**不同的资产、有独立基本面**（矿工股 vs 币、MSTR vs 币）。
#    比值携带真实信息——矿工有自己的 hashprice/电费/增发，跑输币价 = 这门生意在变差。
#    **比值可以当论点退出信号。**
#
#  ②**杠杆型**：跟母体是**同一个资产 × 倍数**（LABU=XBI×3、TQQQ=QQQ×3、SOXL=SMH×3）。
#    比值只是母体**路径形状**的函数（日度复利），**不含任何独立信息**——
#    LABU 跑输 XBI 说不出任何关于生技的事，只说明这段路径是震荡的。
#    **比值不能当论点退出信号。** 实测：LABU/XBI 连续 15 天低于 20 日均值，
#    但同期 LABU/XBI、TQQQ/QQQ、SOXL/SMH 的 120 日漂移分别是 +30.69% / +26.39% / +49.20%
#    （趋势市里复利占优），方向完全由路径决定。
#    杠杆型的退出只能用价格止损（按 ADR 定宽度），不用相对强弱。
PROXY_PARENT = {          # 代理型——比值可用
    "WGMI": "IBIT",       # 比特币矿工 vs 币价本身
    "MSTR": "IBIT",
    "CONL": "COIN",
    "SOXX": "SMH",        # 同类不同编制的半导体ETF，成分权重不同，比值有信息
}
LEVERAGED_NO_RS = {       # 杠杆型——比值无信息，只用价格止损
    "LABU": "XBI", "LABD": "XBI", "TQQQ": "QQQ", "SQQQ": "QQQ",
    "SOXL": "SMH", "SOXS": "SMH", "BITX": "IBIT",
}


def proxy_rs(ticker: str, parent: str = None, ctx=None, lookback: int = 20):
    """代理/杠杆型仓位 vs 母体的比值，及其相对 20 日均值的位置。

    返回 {ticker, parent, ratio, ma, below, days_below, verdict}
      below      当前比值是否低于 20 日均值
      days_below 连续低于均值的天数（触发线=3）
    """
    if ticker in LEVERAGED_NO_RS and not parent:
        return {"ticker": ticker, "parent": LEVERAGED_NO_RS[ticker], "ratio": None,
                "ma": None, "below": None, "days_below": None, "gap_pct": None,
                "verdict": "杠杆型（×倍数），比值是路径函数不含独立信息 → **只用价格止损**"}
    parent = parent or PROXY_PARENT.get(ticker)
    if not parent:
        return None
    from longport.openapi import QuoteContext, Config, Period, AdjustType
    ctx = ctx or QuoteContext(Config.from_apikey_env())

    def closes(t):
        return {str(b.timestamp)[:10]: float(b.close)
                for b in ctx.candlesticks(f"{t}.US", Period.Day, 90, AdjustType.NoAdjust)}

    a, b = closes(ticker), closes(parent)
    days = sorted(set(a) & set(b))
    if len(days) < lookback + 3:
        return None
    ratio = [a[d] / b[d] for d in days]
    mas = [sum(ratio[max(0, i - lookback + 1):i + 1]) / min(lookback, i + 1)
           for i in range(len(ratio))]
    n = 0
    for i in range(len(ratio) - 1, -1, -1):
        if ratio[i] < mas[i]:
            n += 1
        else:
            break
    cur, ma = ratio[-1], mas[-1]
    gap = (cur / ma - 1) * 100
    # 🔴两维触发，缺一不可地互补（2026-08-06 建成当天修）：
    #   纯「连续3天」抓不到 WGMI——它只连续2天，但偏离已 -5.07%（急速走弱）；
    #   纯「偏离幅度」抓不到慢性磨损。**任一满足即触发。**
    if n >= 3 or gap <= -3.0:
        verdict = "🔴论点退出触发（连续%d天 / 偏离%+.2f%%）" % (n, gap)
    elif n >= 1 or gap < 0:
        verdict = "跑输母体（连续%d天 / 偏离%+.2f%%，触发线：3天 或 -3%%）" % (n, gap)
    else:
        verdict = "跟得上母体"
    return {"ticker": ticker, "parent": parent, "ratio": round(cur, 4),
            "ma": round(ma, 4), "below": cur < ma, "days_below": n, "verdict": verdict,
            "gap_pct": round((cur / ma - 1) * 100, 2)}


def proxy_rs_rows(tickers: list, ctx=None) -> dict:
    """给持仓表用的「相对强弱 vs 母体」小表。无母体映射的标的不列。"""
    rows = []
    for t in tickers:
        r = proxy_rs(t, ctx=ctx)
        if not r:
            continue
        if r["ratio"] is None:                      # 杠杆型：不列比值，只列结论
            rows.append([r["ticker"], r["parent"], "—", "—", "—", "—", r["verdict"]])
        else:
            rows.append([r["ticker"], r["parent"], "%.4f" % r["ratio"], "%.4f" % r["ma"],
                         "%+.2f%%" % r["gap_pct"], str(r["days_below"]), r["verdict"]])
    return {"headers": ["TICKER", "母体", "当前比值", "20日均值", "偏离", "连续跑输天数", "判定"],
            "rows": rows, "num_cols": [4], "center_cols": [5], "table_class": "fixed-cols",
            "col_widths": ["10%", "9%", "12%", "12%", "10%", "14%", "33%"]}



# =========================================================================
# 板块 RS 分组的唯一定义（2026-08-06 Vic 改版）
#
# 原来 assemble 是从「上一份报告的 sector_rs_tables」继承分组，改一次要去翻旧 JSON，
# 而且会一路继承下去。改成常量，改这里一处即可。
#
# Vic 2026-08-06 三条：
#   ①「（生技 ≠ XLV）删除」——医疗细分整组去掉
#   ②「科技/AI/半导体/网安/软件 改成半导体细分」——原来那组名字太杂，实际看的是半导体链
#   ③「软件细分单独开一个表格，里面有 igv cibr arkk xsw」
SECTOR_RS_GROUPS = [
    ("指数基准", ["VOO", "QQQ", "DIA", "IWM", "SMH", "RSP", "QQQE"]),
    ("标准板块", ["XLK", "XLI", "XLY", "XLF", "XLE", "XLB", "XLU", "XLRE", "XLV", "XLP", "XLC"]),
    ("半导体细分", ["SMH", "DRAM", "EUV", "SOXX", "QTUM", "AIQ", "MAGS"]),
    ("软件细分", ["IGV", "CIBR", "ARKK", "XSW"]),
    ("主题与国家", ["WGMI", "EWY", "URA", "NASA", "LIT", "TAN", "COPX", "AIRR", "SLV", "JETS",
                    "OIH", "PAVE", "IBIT", "XOP", "GLD", "FXI", "KWEB", "ITA", "XHB", "KRE",
                    "UUP", "IAK"]),
]


# =========================================================================
# 对账清单的事前概率与 Brier 评分（2026-08-08 Vic 抓包）
#
# Vic：「你每天对账为什么都是全中，你每周复盘其实是不对的，对吗」
# 审计 8/3–8/6 共 27 条：真预测只有 10 条（命中 6/10 = 60%），其余 17 条是
#   · 我自己的行为（「今日不建新仓」「XLE 不被误选进候选」）——100% 自控，不是预测
#   · 接近确定（VIX 15.86 时写「VIX<22」；缓冲 +6.54% 时写「不破重置线」）
# 报出来 85%，真预测 60%，差 25 个点。8/5 那个「7/0 满分日」7 条里有 4 条几乎不可能错。
# 更糟的是周报直接累加日报的 hit/miss，把水分放大成「本周框架有效」的结论。
#
# 根因是结构性的：claim 我写、阈值我定、分我打，三个环节没有一条事前难度约束。
# 对照组是 playbook_scenarios——它强制 prob 合计 100 且 QA 会查，所以它没烂。
#
# 三条修正（写成会失败的检查，不是文档条文）：
#   ① 每条 claim 写下时必须带 prob（事前主观概率，0–1 小数）
#   ② 一份 ledger 里 prob >= 0.85 的最多 1 条（留给框架级防线，如 FTD 重置线）；
#      其余必须落在 0.40–0.80。VIX<22 那种缓冲 28% 的条目结构上进不来。
#   ③ 评分改 Brier，不再报裸命中率。prob=0.95 猜中只赚 0.0025，猜错扣 0.9025，
#      堆送分题不再能推高分数——「满分日」在结构上造不出来。
# 另：自控条目 kind="discipline" 单独归类，不进命中率也不进 Brier；
#    它是纪律检查，混进预测里就是白送分。
# Vic 2026-08-08：「裁判还有我肉眼看，不过的确是自己评的太好了」——他是终审，
#    这套约束的作用是别把送分题递到他面前浪费他的时间。
# =========================================================================

# 2026-08-10 Vic：「盘后对账清单 最多写5条好吗？个股不用」
#   · 上限 5 条——台账是给收盘后逐条核对用的，条数一多就没人逐条对
#   · **不放个股**：个股的验证已经有两个更合适的地方（A/B/C 候选表的失效位、
#     事件缺口表的 10% 止损位），放进台账等于同一件事记两遍，还挤掉市场级判断的名额
RECON_MAX = 5
RECON_PROB_MIN, RECON_PROB_MAX = 0.40, 0.80
RECON_PROB_HIGH = 0.85     # >= 此值算「框架级防线」，每份限 1 条
RECON_HIGH_MAX = 1
RECON_MIN_MARKET = 4       # 一份 ledger 至少几条真预测
RECON_OUTCOME = {"hit": 1.0, "partial": 0.5, "miss": 0.0}   # not_triggered 不计分
BRIER_BASELINE = 0.25      # 全填 0.5 的分数 =「我什么都不知道」


def _recon_split(items: list):
    """拆成（真预测, 纪律条目）。kind 缺省视为 market。"""
    items = items or []
    market = [x for x in items if (x.get("kind") or "market") != "discipline"]
    disc = [x for x in items if x.get("kind") == "discipline"]
    return market, disc


# 允许出现在台账里的标的：指数 + 板块/主题 ETF。其余一律视为个股。
_RECON_OK_TICKERS = set(INDEX_ORDER) | {"SPY", "XBI", "IBIT", "TLT", "GLD", "SLV", "USO", "UUP"}
for _g, _ts in SECTOR_RS_GROUPS:
    _RECON_OK_TICKERS |= set(_ts)


def _recon_names_single_stock(item: dict) -> bool:
    """claim 里出现了不在 ETF 白名单里的大写代码 → 判定为押个股。"""
    txt = (item.get("claim") or item.get("plan") or "")
    cands = set(re.findall(r"(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])", txt))
    cands -= {"MA", "ATR", "RSI", "BAM", "FTD", "DTC", "VIX", "CPI", "AI", "EMA",
              "QQQ", "VOO", "T", "Q", "SD"}
    return bool(cands - _RECON_OK_TICKERS)


def validate_recon_ledger(items: list, where: str = "recon_ledger") -> list:
    """返回错误列表，空=通过。assemble 和 qa_report 共用这一处定义。"""
    errs = []
    market, disc = _recon_split(items)
    if len(items or []) > RECON_MAX:
        errs.append("%s: 共 %d 条，**最多 %d 条**（Vic 2026-08-10）——"
                    "条数一多收盘后就没人逐条核对了"
                    % (where, len(items or []), RECON_MAX))
    stock = [x for x in market if _recon_names_single_stock(x)]
    if stock:
        errs.append("%s: 这些条目押的是个股 %s——**个股不进对账台账**（Vic 2026-08-10），"
                    "它们的验证走 A/B/C 的失效位和事件缺口表的止损位"
                    % (where, [ (x.get("claim") or x.get("plan") or "")[:22] for x in stock ]))
    if len(market) < RECON_MIN_MARKET:
        errs.append("%s: 真预测只有 %d 条，至少 %d 条（纪律条目不算）"
                    % (where, len(market), RECON_MIN_MARKET))
    high = []
    for i, it in enumerate(market, 1):
        claim = (it.get("claim") or it.get("plan") or "")[:26]
        p = it.get("prob")
        if p is None:
            errs.append("%s[%d] 缺 prob（写下时的事前概率）：%s" % (where, i, claim))
            continue
        try:
            p = float(p)
        except (TypeError, ValueError):
            errs.append("%s[%d] prob 不是数字：%r" % (where, i, p))
            continue
        if not 0.0 < p < 1.0:
            errs.append("%s[%d] prob=%s 必须是 0–1 的小数（不是百分数）：%s" % (where, i, p, claim))
        elif p >= RECON_PROB_HIGH:
            high.append(claim)
        elif p < RECON_PROB_MIN or p > RECON_PROB_MAX:
            errs.append("%s[%d] prob=%.2f 落在 %.2f–%.2f 之外——太确定的不值得写进对账，"
                        "太离谱的也不该写：%s"
                        % (where, i, p, RECON_PROB_MIN, RECON_PROB_MAX, claim))
    if len(high) > RECON_HIGH_MAX:
        errs.append("%s: prob>=%.2f 的有 %d 条（%s），最多 %d 条——这正是 8/5「7/0 满分日」的造法"
                    % (where, RECON_PROB_HIGH, len(high), "、".join(high), RECON_HIGH_MAX))
    for it in disc:
        if it.get("prob") is not None:
            errs.append("%s: 纪律条目不该带 prob（自控行为不是预测）：%s"
                        % (where, (it.get("claim") or it.get("plan") or "")[:26]))
    return errs


def brier_score(rows: list) -> dict:
    """rows 需带 prob + result。Brier = mean((prob-实际)²)，越低越好。
    同时返回裸命中率，让盘后/周报能把新旧口径并排列出来（差多少一眼可见）。"""
    sq, hard, hits, den, disc, no_prob, untriggered = [], [], 0, 0, 0, 0, 0
    for r in rows or []:
        if (r.get("kind") or "market") == "discipline":
            disc += 1
            continue
        out = RECON_OUTCOME.get(r.get("result"))
        if out is None:
            untriggered += 1
            continue
        den += 1
        if r.get("result") == "hit":
            hits += 1
        p = r.get("prob")
        if p is None:
            no_prob += 1
            continue
        try:
            pf = float(p)
        except (TypeError, ValueError):
            no_prob += 1
            continue
        sq.append((pf - out) ** 2)
        if pf < RECON_PROB_HIGH:
            hard.append((pf - out) ** 2)
    brier = sum(sq) / len(sq) if sq else None
    if brier is None:
        verdict = "无 prob，无法评分"
    elif brier < 0.15:
        verdict = "有信息量（优于「全填50%%」基线 %.3f）" % BRIER_BASELINE
    elif brier < BRIER_BASELINE:
        verdict = "略优于基线 %.3f，信息量有限" % BRIER_BASELINE
    else:
        verdict = "不如「全填50%%」基线 %.3f——判断在帮倒忙" % BRIER_BASELINE
    # 🔴 Brier 是 proper scoring rule，但它**不区分「有技能」和「题目简单」**——
    # 回填 8/5 那天时它给出全周最好的 0.073，恰恰因为那天堆的都是送分题且全中。
    # 所以真正不能被灌水的数字是 brier_hard：只算 prob < 0.85 的条目。
    # 送分题在这个口径下**不产生分数**，只能靠真判断挣。
    brier_hard = sum(hard) / len(hard) if hard else None
    return {
        "brier": brier, "brier_hard": brier_hard, "n_hard": len(hard),
        "n_scored": len(sq), "n_resolved": den,
        "hit_rate": (hits / den) if den else None, "hits": hits,
        "discipline": disc, "no_prob": no_prob, "not_triggered": untriggered,
        "baseline": BRIER_BASELINE, "verdict": verdict,
    }


def brier_note(stats: dict, label: str = "本日", verdict: bool = True) -> str:
    """给盘后/周报用的一句话小结：新旧口径并排，不藏差距。

    🔴 2026-08-09 Vic：「你别改日报了，一天是有很多噪音，周报复盘就好了」
    「我 trading 也是反复的，我了解的」——**评分单位是周，不是日**。
    日频 n≈7，Brier 在这个样本量上就是噪音（0.121 和 0.141 的差别没有意义），
    单日「有信息量 / 不如基线」的判语会诱导过度解读一天的反复。
    所以盘后传 verdict=False：**只记录数字，不下判语**；判语只在周报出（n≈32）。
    """
    if not stats or stats.get("brier") is None:
        return ""
    hr = stats.get("hit_rate")
    hr_txt = ("裸命中率 %d/%d = %.0f%%" % (stats["hits"], stats["n_resolved"], hr * 100)
              if hr is not None else "裸命中率 n/a")
    extra = []
    if stats.get("discipline"):
        extra.append("纪律条目 %d 条不计分" % stats["discipline"])
    if stats.get("not_triggered"):
        extra.append("未触发 %d 条不计分" % stats["not_triggered"])
    tail = ("（%s）" % "、".join(extra)) if extra else ""
    hard = ""
    if stats.get("brier_hard") is not None:
        hard = "｜**真预测 Brier %.3f**（n=%d，剔除 prob>=%.2f 的框架级条目）" % (
            stats["brier_hard"], stats["n_hard"], RECON_PROB_HIGH)
    verd = (stats["verdict"] + "。") if verdict else "**判语见周报**（日频 n 太小，单日读数是噪音）。"
    return ("%s Brier **%.3f**（n=%d，基线 %.2f）%s｜%s。%s%s"
            % (label, stats["brier"], stats["n_scored"], stats["baseline"],
               hard, hr_txt, verd, tail))


def split_positions_by_account(rows: list, positions: list):
    """按账户拆分 positions_rows 的输出。返回 (moomoo_rows, longbridge_rows)。

    2026-08-09 建：原来各报告脚本自己写
        [r for r in rows if any(p["ticker"] == r[0] and p["account"] == "moomoo" for p in positions)]
    ——`any()` 是**按 ticker 匹配**，同一只票在两个账户各有一笔时（MRVL 就是），
    两张表都会把它的两行各收一遍，8/6 那份报告里 MRVL 出现了 4 次。
    rows 与 positions 本来就是 1:1 同序的，直接 zip 即可。
    """
    mm, lb = [], []
    for r, p in zip(rows, positions):
        (mm if p.get("account") == "moomoo" else lb).append(r)
    return mm, lb


# =========================================================================
# 轧空面板（2026-08-09 重建，Vic：「轧空我发现 groupon 和 wolf，我觉得那个板块
# 还是有用的…就是要找办法解决数据问题」）
#
# 旧数据源 iborrowdesk 整周 403，面板一周没有真实数据。改用两个 FINRA 免费端点，
# 都不需要 key、不需要登录：
#   ① 合并短仓（双周结算，T+约10个工作日）——空仓量、日均量、**days to cover**
#   ② 每日做空量 CNMSshvol（T+1）——当日做空量占总量的比例
# 试过并排除的：iborrowdesk（连接被关）、IBKR usa.txt（ftp3 超时 / download2 404）、
# Nasdaq 短仓 API（只支持 Nasdaq 上市，WOLF 在 NYSE 拿不到）、stockanalysis（404）。
# **借券费/使用率仍然没有免费源**——面板不假装有这一列，缺就是缺。
#
# 三段判据（8/9 用 WOLF / GRPN 双样本定的）：
#   燃料：DTC >= 5 且最近一期空仓没有明显下降（空头被困在低流动性里）
#   点火：单日大阳、收盘位置 >= 80%、量 >= 1.2×
#   续航：**上涨日的做空占比不降反升 = 空头还在抵抗，轧空没走完**
#
# 双样本对照（这是判据的来源，别删）：
#   WOLF 7/15 DTC 6.79（自 5/15 的 2.19 一路升，空仓 +0.34% 没减）
#        → 7/30 +18.59% / 8/4 +11.13% / 8/6 +9.53% / 8/7 **+19.14%**
#        且做空占比 34%→49%→**59.3%**（8/7 那根大阳当天最高）= 空头加码对抗
#   GRPN 7/15 DTC 9.13（更高，且空仓 +11.87% 空头在加）
#        → 却是 8/6 -7.84%、8/7 收盘位置 15%，放量往下
#        做空占比常年 45~72% 但股价在跌 = **空头是对的**
#   🔴结论：**高空头比例只是燃料，不是信号。** 没有点火的高 DTC 是「空头正确」，
#   不是「即将轧空」——GRPN 就是这个反例，不要因为 DTC 高就把它放进候选。
# =========================================================================

FINRA_SI_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
FINRA_SHVOL_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol%s.txt"
SQUEEZE_DTC_MIN = 5.0
SQUEEZE_RANGE_POS_MIN = 80
SQUEEZE_VOL_MIN = 1.2


def _http(url, body=None, timeout=25):
    import urllib.request, ssl
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE
    h = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if body is not None:
        h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h)
    else:
        req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=c).read()


def finra_short_interest(ticker: str, since: str = None, limit: int = 60) -> list:
    """双周合并短仓。返回按结算日升序的 [{date, short, adv, dtc, chg_pct}]，失败返回 []。

    🔴 FINRA 返回是**升序**且 limit 从头截断——`since` 给早了会拿到最旧的几期而不是最新的。
    （8/9 第一次跑就踩到：since=2026-01-01 + limit=12 取到 6/30，把 WOLF 的 DTC 读成 3.85，
    真值是 7/15 的 6.79，判定直接反了。）所以 since 默认只回看 180 天。"""
    if since is None:
        from datetime import date, timedelta
        since = (date.today() - timedelta(days=180)).isoformat()
    body = {"limit": limit, "compareFilters": [
        {"fieldName": "symbolCode", "fieldValue": ticker, "compareType": "EQUAL"},
        {"fieldName": "settlementDate", "fieldValue": since, "compareType": "GTE"}]}
    try:
        raw = json.loads(_http(FINRA_SI_URL, body))
    except Exception:
        return []
    out = [{"date": r["settlementDate"], "short": r.get("currentShortPositionQuantity"),
            "adv": r.get("averageDailyVolumeQuantity"), "dtc": r.get("daysToCoverQuantity"),
            "chg_pct": r.get("changePercent"), "exchange": r.get("marketClassCode")}
           for r in raw]
    return sorted(out, key=lambda x: x["date"])


def finra_short_volume(tickers, dates: list) -> dict:
    """每日做空量占比。dates 是 'YYYYMMDD' 列表。返回 {ticker: [(date, pct), ...]}。
    一天一个文件（约 540KB），所以调用方自己控制天数——别一次拉三个月。"""
    want = set(tickers)
    out = {t: [] for t in want}
    for ds in dates:
        try:
            txt = _http(FINRA_SHVOL_URL % ds).decode()
        except Exception:
            continue
        for ln in txt.splitlines()[1:]:
            p = ln.split("|")
            if len(p) >= 5 and p[1] in want:
                try:
                    sv, tv = float(p[2]), float(p[4])
                except ValueError:
                    continue
                if tv:
                    out[p[1]].append((p[0], round(sv / tv * 100, 1)))
    return out


def squeeze_read(ticker: str, cache: dict = None, sv_series: list = None,
                 si_series: list = None) -> dict:
    """把三段判据合成一个判定。cache 提供当日的 t1_pct / range_pos / vol_ratio。

    返回 {ticker, dtc, short_trend, fuel, ignition, persistence, verdict}
    verdict 只有四种，措辞是单向的（不写「但是」）：
      **轧空进行中**   燃料+点火+续航 三段齐
      **点火未续航**   涨了但做空占比在降 → 空头在平，追的是尾声
      **有燃料无点火** DTC 够高但没有大阳线 → 这是「空头正确」不是「即将轧空」
      **不在池内**     燃料不足
    """
    m = (cache or {}).get("metrics", {}).get(ticker, {}) if cache else {}
    si = si_series if si_series is not None else finra_short_interest(ticker)
    dtc = si[-1]["dtc"] if si else None
    # 空仓趋势：最近一期相对上一期
    short_trend = None
    if len(si) >= 2 and si[-2]["short"]:
        short_trend = (si[-1]["short"] - si[-2]["short"]) / si[-2]["short"] * 100
    fuel = bool(dtc and dtc >= SQUEEZE_DTC_MIN and (short_trend is None or short_trend > -10))

    t1, pos, vr = m.get("t1_pct"), m.get("range_pos"), m.get("vol_ratio")
    ignition = bool(t1 and t1 > 0 and pos is not None and pos >= SQUEEZE_RANGE_POS_MIN
                    and vr and vr >= SQUEEZE_VOL_MIN)
    # 续航：上涨日做空占比不降反升
    persistence = None
    if sv_series and len(sv_series) >= 3:
        last, prior = sv_series[-1][1], sum(x[1] for x in sv_series[-4:-1]) / 3
        persistence = last >= prior
    if not fuel:
        verdict = "**不在池内**（DTC %s 未达 %.1f）" % (dtc, SQUEEZE_DTC_MIN)
    elif not ignition:
        verdict = ("**有燃料无点火**（DTC %.2f）——这是「空头正确」不是「即将轧空」，"
                   "GRPN 就是这个反例" % dtc)
    elif persistence is False:
        verdict = "**点火未续航**——做空占比在上涨日回落，空头在平仓，追的是尾声"
    else:
        verdict = "🎯**轧空进行中**（DTC %.2f，做空占比在上涨日仍升）" % dtc
    return {"ticker": ticker, "dtc": dtc, "short_trend": short_trend, "fuel": fuel,
            "ignition": ignition, "persistence": persistence, "verdict": verdict,
            "sv_last": sv_series[-1][1] if sv_series else None}


# --- 轧空面板：筛选方向必须是「先点火再查燃料」（2026-08-10 定）------------
# 第一版按 DTC>=5 全市场筛，7/15 那期出来 384 只（日均量>=50万且空仓在增加），
# 前 30 名全是 REIT（MPT/EPR/MAIN）、封闭式基金（CLM/CRF）和微盘生物（LCTX/IPSC）——
# 这些标的的高空头比例是**结构性的**（分红套利、折价套利），不是有人在赌它跌。
# 而 GRPN 已经证明：**燃料本身不是信号**（DTC 9.13 却放量往下）。
# 所以顺序反过来：**先用价格找点火（大阳收在区间高位+放量），再回查它有没有燃料。**
# 燃料表一期只变一次（双周结算），落盘缓存，不用每天拉。
SQUEEZE_MIN_ADV = 1_000_000        # 日均量门槛，低于此的轧空追不进也出不来

def squeeze_fuel_table(refresh: bool = False) -> dict:
    """全市场 DTC 查询表 {ticker: {dtc, short, adv, chg_pct, date}}，落盘缓存。
    双周结算，一期只变一次，所以默认读缓存。"""
    from datetime import date, timedelta
    p = ROOT / "data" / "cache" / "short_interest_latest.json"
    if p.exists() and not refresh:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    # 🔴 FINRA 每次最多返回 5000 行且是**升序**——limit 给大没用，会被截在字母表前段
    #    （8/10 第一次跑：limit=20000 只拿到 A–B 开头的票，WOLF/GRPN 全部 n/a）。
    #    所以必须①先定位最新结算日 ②锁定那一天 ③用 offset 翻页。
    # 探最新结算日必须用**单只票**过滤——不加符号过滤时首页是字母表前 5000 行，
    # 它们的最新一期未必已发布，max() 会拿到上一期（8/10 踩到：拿成 6/30，真值 7/15，
    # 结果全表 DTC 都是过期的，WOLF 读成 3.85 而不是 6.79）。
    since = (date.today() - timedelta(days=60)).isoformat()
    latest = ""
    for probe_sym in ("AAPL", "MSFT", "F"):
        try:
            raw = json.loads(_http(FINRA_SI_URL, {"limit": 20, "compareFilters": [
                {"fieldName": "symbolCode", "fieldValue": probe_sym, "compareType": "EQUAL"},
                {"fieldName": "settlementDate", "fieldValue": since, "compareType": "GTE"}]}))
        except Exception:
            continue
        latest = max([latest] + [(r.get("settlementDate") or "") for r in raw])
    if not latest:
        return {}
    tbl, off = {}, 0
    while True:
        body = {"limit": 5000, "offset": off, "compareFilters": [
            {"fieldName": "settlementDate", "fieldValue": latest, "compareType": "EQUAL"}]}
        try:
            page = json.loads(_http(FINRA_SI_URL, body, timeout=90))
        except Exception:
            break
        if not page:
            break
        for r in page:
            sym = r.get("symbolCode")
            if not sym:
                continue
            tbl[sym] = {"dtc": r.get("daysToCoverQuantity"),
                        "short": r.get("currentShortPositionQuantity"),
                        "adv": r.get("averageDailyVolumeQuantity"),
                        "chg_pct": r.get("changePercent"),
                        "date": r.get("settlementDate"), "exchange": r.get("marketClassCode")}
        off += len(page)
        if len(page) < 5000:
            break
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tbl, ensure_ascii=False), encoding="utf-8")
    return tbl


def squeeze_rows(tickers, cache: dict, sv: dict = None, fuel: dict = None) -> dict:
    """给盘前用的轧空表。tickers 是**已经点了火的候选**（涨幅/异动扫描出来的），
    这里只回查燃料和续航——不要反过来用 DTC 去生成候选。"""
    fuel = squeeze_fuel_table() if fuel is None else fuel
    rows = []
    for t in tickers:
        f = fuel.get(t)
        if not f or not f.get("dtc"):
            continue
        if (f.get("adv") or 0) < SQUEEZE_MIN_ADV:
            continue
        r = squeeze_read(t, cache=cache, sv_series=(sv or {}).get(t),
                         si_series=[{"date": f["date"], "short": f["short"], "dtc": f["dtc"],
                                     "adv": f["adv"], "chg_pct": f["chg_pct"]}])
        m = (cache or {}).get("metrics", {}).get(t, {})
        # 渲染层 build_squeeze_table 读的是 dict 键，不是位置列表——
        # 键名对不上会在渲染时抛 AttributeError（2026-08-10 踩过一次）。
        # 借券费率那一列没有免费源，统一写「无免费源」而不是留空或编数。
        rows.append({
            "ticker": t,
            "short_pct_float": "DTC %.2f" % f["dtc"],
            "days_to_cover": "%.2f" % f["dtc"],
            "borrow_fee": "无免费源",
            "short_volume_trend": ("做空占比 %.1f%%" % r["sv_last"]) if r.get("sv_last") is not None else "-",
            "catalyst": ("T-1 %+.2f%% · 收盘位置 %d%% · 空仓%+.1f%%"
                         % (m.get("t1_pct") or 0, m.get("range_pos") or 0, f.get("chg_pct") or 0)),
            "status": r["verdict"],
            "_dtc": f["dtc"]})
    rows.sort(key=lambda x: -x["_dtc"])
    for x in rows:
        x.pop("_dtc", None)
    return rows


# =========================================================================
# Deemer Breakaway Momentum（2026-08-10 上线，Vic：「deemer 开始读」）
#
# 定义：10 日 advances 之和 ÷ 10 日 declines 之和 > 1.97。
# Deemer 本人的话是「重点不是涨的家数多，是跌的家数少」——所以它是**分母信号**，
# 不是分子信号。这跟 FTD 那套「涨幅+放量」的分子逻辑正好互补，也是 Vic 8/6 停掉 FTD
# 之后想试它的原因。
#
# 🔴数据口径的两个诚实说明（不要在报告里假装它是原版）：
#   ① Deemer 的原始口径是 **NYSE** 涨跌家数。我们这个源是更宽的美股全市场
#      （约 2400 只），家数基数不同，**1.97 这个阈值不能想当然照搬**。
#      所以 bam_reading() 同时返回历史分位，用「这个读数在自己的历史里排第几」来读，
#      而不是只看有没有过 1.97。
#   ② 数据来自 combined_breadth.history（Vic 的 Google Sheet），只有约 23 天，
#      **一年分位算不出来**，分位是在现有窗口内算的。窗口会随每天累积变长。
# =========================================================================

BAM_WINDOW = 10
BAM_THRESHOLD = 1.97


def bam_series(cache: dict, window: int = BAM_WINDOW) -> list:
    """返回按日期升序的 [{date, adv10, dec10, ratio}]。不足 window 天则返回 []。"""
    hist = ((cache or {}).get("combined_breadth") or {}).get("history") or []
    rows = sorted([r for r in hist if r.get("advance") and r.get("decline")],
                  key=lambda r: r["date"])
    out = []
    for i in range(window - 1, len(rows)):
        w = rows[i - window + 1:i + 1]
        a = sum(r["advance"] for r in w)
        d = sum(r["decline"] for r in w)
        out.append({"date": rows[i]["date"], "adv10": a, "dec10": d,
                    "ratio": round(a / d, 3) if d else None})
    return out


def bam_reading(cache: dict) -> dict:
    """当日 BAM 读数 + 在现有窗口里的分位 + 单向判语。"""
    s = bam_series(cache)
    if not s:
        return {"ratio": None, "verdict": "**数据不足**（A/D 历史不满 %d 天）" % BAM_WINDOW}
    cur = s[-1]
    vals = sorted(x["ratio"] for x in s if x["ratio"] is not None)
    pct = int(round(sum(1 for v in vals if v <= cur["ratio"]) / len(vals) * 100))
    peak = max(vals)
    if cur["ratio"] >= BAM_THRESHOLD:
        verdict = ("🎯**BAM 触发**（%.2f ≥ %.2f）——10 日跌的家数少到极值，"
                   "Deemer 口径的推力信号成立" % (cur["ratio"], BAM_THRESHOLD))
    elif pct >= 80:
        verdict = ("**未触发但在自身高位**（%.2f，样本内第 %d 分位，窗口峰值 %.2f）——"
                   "分母在收缩，方向对，幅度不够" % (cur["ratio"], pct, peak))
    else:
        verdict = ("**未触发**（%.2f，样本内第 %d 分位）——跌的家数没有少到 Deemer 要的程度"
                   % (cur["ratio"], pct))
    return {"date": cur["date"], "ratio": cur["ratio"], "adv10": cur["adv10"],
            "dec10": cur["dec10"], "pctile": pct, "peak": peak, "n": len(s),
            "threshold": BAM_THRESHOLD, "verdict": verdict, "series": s}
