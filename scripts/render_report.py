#!/usr/bin/env python3
"""Render a premarket report JSON (see templates/data_schema.md) into a styled
static HTML file, visually modeled on the sintszkay market-reports layout.

Usage:
    python render_report.py data/daily/2026-07-04-premarket.json
    python render_report.py data/daily/2026-07-04-premarket.json --out output/premarket/custom.html
"""
import argparse
import html
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "templates" / "report.css"

# 对账评分的口径（RECON_OUTCOME / Brier 阈值）只在 report_helpers 定义一处，
# 渲染层引用而不复制——复制过一次就会漂（板块 RS 分组那次的教训）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_helpers as _RH  # noqa: E402

LEVEL_TO_BADGE = {"low": "green", "mid": "amber", "high": "red"}


# 2026-07-28 Vic：「报告中还是有很多红绿灯」——第三次提了。前两次都当"写作时收着点用"交给
# assemble自觉，结果每天重新长出来：真源头是 report_helpers 里20处硬编码进生成文本的
# 🔴/🟢（"🔴买点作废"、"🔴盘前警报"…），不是哪天手滑。所以收口放渲染层——唯一出口、绕不过去。
# 只剥字符不换成带色span：esc()的输出也进HTML属性（badge kind、anchor等），插标签会污染属性。
# 严重度本来就有CSS在表达（badge配色 / callout kind / sign_class涨跌色 / result徽章），emoji是第四层冗余。
_LIGHTS_RE = re.compile("[🔴🟢🟡🟠⚪⚫✅❌]|⚠️?")


def strip_lights(value: str) -> str:
    return _LIGHTS_RE.sub("", str(value)).strip()


def esc(value) -> str:
    return html.escape(strip_lights(value), quote=True)


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def rich(value) -> str:
    """长句富文本：先esc()保证安全，再把写作时用的极少数markdown记号变成真排版。
    2026-07-22 Vic："小结格式都改好点啊，不分行目前很难读的"——根因有两个，一是没分行，
    二是**粗体**一直当字面星号渲染（当天一份报告里有214处literal `**`）。
    支持：**加粗** / 空行分段 / 单换行断行。只注入strong/br/p三种安全标签，其余仍是转义文本。"""
    if value is None:
        return ""
    s = esc(value)
    s = _BOLD_RE.sub(r"<strong>\1</strong>", s)
    paras = [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]
    if not paras:
        return ""
    if len(paras) == 1:
        return paras[0].replace("\n", "<br>")
    return "".join(f'<p style="margin:0 0 8px">{p.replace(chr(10), "<br>")}</p>'
                   for p in paras).rstrip()


def tri(escaped: str) -> str:
    """▲/▼ 三角自动着色（2026-07-11 Vic要求：MA上下方不写"上/下"，用红绿三角）。
    在esc()之后调用，只注入这两个固定的安全span。"""
    return escaped.replace("▲", '<span class="up">▲</span>').replace("▼", '<span class="dn">▼</span>')


def build_ma_cell(raw: str) -> str:
    """Above MA(20/50/200)独立小chip（2026-07-21对标老师报告格式改版，取代纯▲▼文本）。
    输入是report_helpers.tri3()产出的"20▲ 50▲ 200▼"格式（period+箭头，空格分隔）；
    输出<span class="ma">每个period各自一个<b class="up/dn">N<i>▲/▼</i></b></span>。
    这里直接吃原始文本自己转义数字部分，不依赖调用方先esc()——cell内容本身只有数字/字母/▲▼，
    不会有需要转义的HTML特殊字符。"""
    parts = []
    for tok in str(raw).split():
        arrow = tok[-1] if tok and tok[-1] in ("▲", "▼") else None
        period = esc(tok[:-1] if arrow else tok)
        if arrow == "▲":
            parts.append(f'<b class="up">{period}<i>▲</i></b>')
        elif arrow == "▼":
            parts.append(f'<b class="dn">{period}<i>▼</i></b>')
        else:
            parts.append(f'<b>{period}<i>-</i></b>')
    return f'<span class="ma">{"".join(parts)}</span>'


def sign_class(cell: str) -> str:
    s = str(cell).strip()
    if s in ("", "-", "—", "N/A"):
        return ""
    if s.startswith("+"):
        return "up"
    if s.startswith("-"):
        return "dn"
    return ""


ROW_HIGHLIGHT_CLASS = {"bull": "row-bull", "warn": "row-warn", "band": "row-band",
                       "mute": "row-mute",
                       # 2026-08-18 Vic：「需要执行的仓位…标识黄色底」
                       "act": "row-act"}


def build_table(table: dict) -> str:
    """row_highlights（可选，与rows等长，值为"bull"/"warn"/""）：给宏观表格里出现
    预警或超级看多的行加红/绿底色，方便一眼扫到，而不是所有行看起来都一样。
    ma_cols（可选，2026-07-21新增）：列内容是report_helpers.tri3()产出的"20▲ 50▲ 200▼"格式，
    渲成Above MA独立小chip（见build_ma_cell），不走num_cols/常规转义路径。
    raw_cols（可选，2026-07-21新增）：列内容已经是assemble脚本用report_helpers.badge()等
    组装好的安全HTML（比如Beat/Miss彩色标签），原样输出不再esc()——调用方对这列内容的HTML
    安全性负责，不能塞入未经处理的外部数据。
    table_class + col_widths（可选，2026-07-27新增，Vic："第一组/第二组/第三组是同样的表格格式，
    他们应该都对齐的"）：同一组多张表各自按内容自适应列宽会导致视觉不齐；给它们同一个table_class
    并配一组col_widths（<colgroup>），就能强制三张表列宽一致。表头一律nowrap不换行。"""
    if not table:
        return ""
    headers = table.get("headers", [])
    rows = table.get("rows", [])
    num_cols = set(table.get("num_cols", []))
    center_cols = set(table.get("center_cols", []))
    ma_cols = set(table.get("ma_cols", []))
    raw_cols = set(table.get("raw_cols", []))
    # badge_cols（2026-07-28新增，Vic：「延续 如果是 用绿色标签」）：把是/否类的短判定
    # 渲成彩色chip——是=绿、否=灰，其余原样。
    badge_cols = set(table.get("badge_cols", []))
    highlights = table.get("row_highlights", [])
    table_class = table.get("table_class", "")
    col_widths = table.get("col_widths", [])
    if not rows:
        return f'<p class="placeholder">暂无数据。</p>'
    # 2026-08-07：没给 col_widths 就自动生成一组，不再让"裸表"出现。
    # 起因是 Vic 指出 QA 的毛病——「表格列宽对齐」这条 56 份报告里报了 45 次、
    # 一次都没被修过（我把它设成 fatal=False 然后天天忽略）。**靠"以后记得写"是修不掉的**，
    # 只能在渲染层兜底：第一列窄（ticker/日期）、最后一列宽（判断/备注类长文本）、中间等分。
    # assemble 侧显式给的 col_widths 永远优先，这里只兜没给的情况。
    if not col_widths and headers:
        n = len(headers)
        if n == 1:
            col_widths = ["100%"]
        elif n == 2:
            col_widths = ["30%", "70%"]
        else:
            first, last = 9, 32 if n >= 5 else 26
            mid = round((100 - first - last) / (n - 2), 2)
            col_widths = [f"{first}%"] + [f"{mid}%"] * (n - 2) + [f"{last}%"]
    # 🔴 2026-08-20：fixed-cols 原来只在**自动兜底**那条分支上补。
    #    assemble 侧显式写了 col_widths 的表走另一条路，class 一直是空的，
    #    渲出来就是裸 <table>——「表格列宽对齐」那条 QA 当场报错。
    #    **给了列宽就一定要给 fixed-cols**，否则 colgroup 的宽度不生效（表还是自适应）。
    if col_widths:
        table_class = table_class or "fixed-cols"
    colgroup = ("<colgroup>" + "".join(f'<col style="width:{w}">' for w in col_widths) + "</colgroup>") if col_widths else ""
    tbl_attr = f' class="{esc(table_class)}"' if table_class else ""
    def _hcls(i):
        # badge_cols的单元格是居中的chip，表头必须一起居中，否则标题和标签对不齐
        # （2026-07-29 Vic抓到：「绿色的是那一列和 延续 标题对齐」）
        if i in num_cols:
            return "num"
        return "ctr" if (i in center_cols or i in badge_cols) else ""
    thead = "".join(f'<th class="{_hcls(i)}">{esc(h)}</th>' for i, h in enumerate(headers))
    # 组标题行（2026-07-27 Vic："市宽表格很长了，能不能再分板块"）：整行合并成一条深色带，
    # 后面的数据行用row_highlights="band"上浅蓝底，把长表切成可扫读的区块。
    group_rows = set(table.get("group_header_rows", []))
    body_rows = []
    for ri, row in enumerate(rows):
        if ri in group_rows:
            body_rows.append(f'<tr class="row-group"><td colspan="{len(headers)}">{esc(row[0])}</td></tr>')
            continue
        cells = []
        for i, cell in enumerate(row):
            if i in ma_cols:
                cells.append(f'<td class="ma-cell">{build_ma_cell(cell)}</td>')
            elif i in raw_cols:
                cells.append(f"<td>{cell}</td>")
            elif i in badge_cols:
                v = strip_lights(str(cell)).strip()
                bcls = {"是": "yn-yes", "否": "yn-no"}.get(v, "")
                inner = f'<span class="yn {bcls}">{esc(v)}</span>' if bcls else esc(v)
                cells.append(f'<td class="ctr">{inner}</td>')
            elif i in num_cols:
                cls = f"num {sign_class(cell)}".strip()
                cells.append(f'<td class="{cls}">{tri(rich(cell))}</td>')
            elif i in center_cols:
                cells.append(f'<td class="ctr">{tri(rich(cell))}</td>')
            else:
                # rich()而非esc()：判断/说明类长文本列常带**加粗**（2026-07-22 Vic反馈修的同一个坑），
                # 数字/ticker类短cell不受影响（rich对无**、无空行的普通短字符串等价于esc）
                cells.append(f"<td>{tri(rich(cell))}</td>")
        row_cls = ROW_HIGHLIGHT_CLASS.get(highlights[ri] if ri < len(highlights) else "", "")
        tr_attr = f' class="{row_cls}"' if row_cls else ""
        body_rows.append(f"<tr{tr_attr}>{''.join(cells)}</tr>")
    return (f"<table{tbl_attr}>{colgroup}<thead><tr>{thead}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>")


def build_summary_cards(cards: list) -> str:
    if not cards:
        return ""
    items = []
    for c in cards:
        # note是整句判断，常带**加粗**——必须用rich()（2026-07-30 QA第4条抓到）
        note = f'<p class="note">{rich(c["note"])}</p>' if c.get("note") else ""
        items.append(
            f'<div class="card"><span>{esc(c["label"])}</span>'
            f'<strong class="{sign_class(c["value"])}">{esc(c["value"])}</strong>{note}</div>'
        )
    return f'<section class="grid">{"".join(items)}</section>'


SEVERITY_BLOCKS = {"low": 2, "mid": 3, "high": 5}


def build_risk_bars(items: list) -> str:
    """2026-07-27 Vic："这个表格不用再增加'红灯'，深红色已经很明显"——去掉顶部那条
    低/中/高计数汇总条（severity色块本身已经把强弱说清楚了，再加一条统计是冗余）。"""
    if not items:
        return ""
    summary = ""
    rows = []
    for it in items:
        level = it.get("level", "mid")
        n = SEVERITY_BLOCKS.get(level, 3)
        blocks = "".join("<i></i>" for _ in range(5))
        rows.append(
            '<div class="risk-row">'
            f'<span class="risk-label">{esc(it.get("label",""))}</span>'
            f'<span class="severity {esc(level)}">{blocks}</span>'
            f'<span class="risk-detail">{rich(it.get("detail",""))}</span>'
            "</div>"
        )
    return summary + f'<div class="risk-rows">{"".join(rows)}</div>'


TYPE_LABEL = {"upgrade": "升级", "downgrade": "降级", "duration": "防线", "techparity": "标配"}


def build_scoreboard_table(rows: list) -> str:
    """状态颜色永远代表"对多头有利/不利"的方向，跟条件本身是升级还是降级无关：
    升级/标配类：met=绿(已满足) / unmet=灰(未满足)；
    降级/防线类：triggered=红(已触发，坏消息) / safe=绿(安全，未触发)。
    这样表格不会因为"降级条件未触发"也显示模糊的灰色而让人误读方向。"""
    if not rows:
        return '<p class="placeholder">暂无数据。</p>'
    STATUS_CLASS = {"met": "status-met", "unmet": "status-unmet", "triggered": "status-triggered", "safe": "status-safe"}
    STATUS_LABEL = {"met": "已满足", "unmet": "未满足", "triggered": "已触发", "safe": "安全"}
    body_rows = []
    for r in rows:
        status = r.get("status", "unmet")
        cls = STATUS_CLASS.get(status, "status-unmet")
        label = STATUS_LABEL.get(status, status)
        rtype = r.get("type", "")
        type_label = TYPE_LABEL.get(rtype, rtype)
        # 2026-07-12 Vic："攻守计分板，整行填色"——triggered=整行红底，met/safe=整行绿底
        row_cls = "row-warn" if status == "triggered" else ("row-bull" if status in ("met", "safe") else "")
        tr_attr = f' class="{row_cls}"' if row_cls else ""
        body_rows.append(
            f"<tr{tr_attr}>"
            f"<td>{esc(r.get('condition',''))}</td>"
            f'<td class="type-col">{esc(type_label)}</td>'
            f'<td class="num">{esc(r.get("threshold",""))}</td>'
            f'<td class="num">{esc(r.get("current",""))}</td>'
            # 前值/变化：2026-07-31 删掉重复的「A·市宽」后，把它独有的两列并到这里，信息不丢
            f'<td class="num">{esc(r.get("prev",""))}</td>'
            f'<td class="num {sign_class(r.get("chg",""))}">{esc(r.get("chg",""))}</td>'
            f'<td class="num {sign_class(r.get("distance_pct",""))}">{esc(r.get("distance_pct",""))}</td>'
            f'<td class="{cls}">{esc(label)}</td>'
            "</tr>"
        )
    return (
        '<table class="scoreboard-table"><thead><tr>'
        "<th>条件</th><th>类型</th><th class=\"num\">门槛</th><th class=\"num\">当前值</th>"
        "<th class=\"num\">前值</th><th class=\"num\">变化</th>"
        "<th class=\"num\">距门槛%</th><th>状态</th>"
        "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


TREND_TAG_CLASS = {"下降": "down", "临界": "critical", "横盘偏强": "strong", "相对强": "strong"}


def build_atr_extension_table(rows: list) -> str:
    """指数50MA ATR延伸表（2026-07-27新增，借鉴Vic老师报告的"距50MA(ATR)+趋势"格式，Vic反馈
    "我们的报告整体缺乏趋势"）。行数据来自report_helpers.atr_extension_rows()。
    沿用项目既有色系（红=走弱/绿=走强，不引入黄棕色），条形用.atr-cell，趋势标签用.trend-tag。"""
    if not rows:
        return '<p class="placeholder">暂无数据。</p>'
    body = []
    for r in rows:
        dist = r.get("dist_ma50_atr")
        if dist is None:
            bar = "-"
        else:
            a = abs(dist)
            level = 0 if a < 0.3 else 1 if a < 0.75 else 2 if a < 1.2 else 3 if a < 2.0 else 4
            direction = "up" if dist >= 0 else "dn"
            blocks = "".join("<b></b>" for _ in range(4))
            bar = f'<span class="atr-cell {direction} l{level}"><i>{blocks}</i><em>{dist:+.2f}</em></span>'
        trend = r.get("trend", "")
        tcls = TREND_TAG_CLASS.get(trend, "critical")
        body.append(
            "<tr>"
            f"<td>{esc(r.get('ticker',''))}</td>"
            f'<td class="num">{esc(r.get("close",""))}</td>'
            f'<td class="num">{esc(r.get("ma50",""))}</td>'
            f'<td class="num">{esc(r.get("atr14",""))}</td>'
            f'<td class="num">{bar}</td>'
            f'<td><span class="trend-tag {tcls}">{esc(trend)}</span></td>'
            f"<td>{esc(r.get('judgment',''))}</td>"
            "</tr>"
        )
    return (
        '<table class="atr-ext-table"><thead><tr>'
        "<th>指标</th><th class=\"num\">价格</th><th class=\"num\">50MA</th><th class=\"num\">ATR(14)</th>"
        "<th class=\"num\">距50MA ATR</th><th>趋势</th><th>判断</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


def build_regime_triggers(rt: dict) -> str:
    if not rt:
        return ""
    up = rt.get("upgrade", {})
    dn = rt.get("downgrade", {})
    up_items = "".join(f"<li>{esc(x)}</li>" for x in up.get("items", []))
    dn_items = "".join(f"<li>{esc(x)}</li>" for x in dn.get("items", []))
    return f"""<section class="regime-triggers">
  <div class="trigger-box trigger-upgrade">
    <div class="tb-header"><span class="tb-arrow">&uarr;</span><span class="tb-label">油门升级讯号</span><span class="tb-sub">转攻击</span></div>
    <div class="tb-rule">{esc(up.get("rule", ""))}</div>
    <ul class="tb-list">{up_items}</ul>
  </div>
  <div class="trigger-box trigger-downgrade">
    <div class="tb-header"><span class="tb-arrow">&darr;</span><span class="tb-label">油门降级讯号</span><span class="tb-sub">转防守</span></div>
    <div class="tb-rule">{esc(dn.get("rule", ""))}</div>
    <ul class="tb-list">{dn_items}</ul>
  </div>
</section>"""


def build_callout(kind: str, text: str, label: str = "") -> str:
    # 🔴 2026-08-20：默认标题一并去掉。build_split_callout 在段数 ≤2 时会转调这里，
    #    如果只改一边，就变成「短小结带标题、长小结不带」——同一个东西两种长相，
    #    那是格式漂移的经典起点。
    """2026-07-12 Vic："小结统一都用蓝色装饰，红色绿色很刺眼"——kind参数保留兼容旧调用，
    但一律渲染成蓝色基础callout。2026-07-22起正文走rich()：支持**加粗**与空行分段。

    🔴 2026-08-17 加 label：build_split_callout 的 label="" 此前只在「≥3 段」那条
       分支上生效，段数少时掉进这里、标题行又冒出来。Vic 当天抓到的就是这个——
       D·其他资产（陈述）和它下面的联合信号（真小结）连着两个「小结：」。"""
    if not text:
        return ""
    head = f"<strong>{esc(label)}：</strong>" if label else ""
    return f'<div class="callout">{head}{rich(text)}</div>'


def _split_outside_bold(text: str, sep: str) -> list:
    """按 sep 切，但**不切在 `**…**` 里面**。

    🔴 2026-08-14 建。起因：8/13 盘后的 ml_tomorrow_watch 里有一句
       `**明日核心矛盾：……不是财报点起来的；而当天有三份真财报……全部被卖。**`——
       粗体跨了一个全角分号，旧写法 `text.split(sep)` 从中间切开，
       两半各拿到一个落单的 `**`，rich() 配不上对，**两个星号原样渲染到页面上**。
       QA 的「literal ** 星号」那条抓到了，但这是渲染层的锅不是写作的锅：
       小结里出现「……；……」本来就是最自然的中文写法，不该要求作者绕开它。
    """
    out, buf, bold, i = [], [], False, 0
    while i < len(text):
        if text.startswith("**", i):
            bold = not bold
            buf.append("**")
            i += 2
            continue
        if not bold and text.startswith(sep, i):
            out.append("".join(buf))
            buf = []
            i += len(sep)
            continue
        buf.append(text[i])
        i += 1
    out.append("".join(buf))
    return out


def build_bam_chart(tbl: dict, bam: dict) -> str:
    """Deemer BAM 比值折线图（2026-08-14 建，Vic：「只显示2天，或者你做成图表」）。

    取代原来的 10 行逐日表格——那张表只有最后一行有判语，前 9 行纯粹是让眼睛找趋势，
    而找趋势本来就该交给图。画三样东西：
      · 比值折线（每个点带日期，最后一点加粗标数）
      · **触发阈值线**（BAM_THRESHOLD 1.97，虚线）——「离触发还有多远」一眼可见
      · 1.0 基准线（涨跌家数持平）

    纯内联 SVG，不引外部库；颜色全部走报告自己的 CSS 变量，深浅色主题都能看。
    y 轴范围按数据自适应，但**下界不高于 1.0、上界不低于阈值**——否则阈值线会跑出画布，
    「差多远」这个唯一重点就丢了。
    """
    rows = tbl.get("rows") or []
    pts = []
    for r in rows:
        try:
            pts.append((str(r[0]), float(r[3])))
        except (ValueError, TypeError, IndexError):
            continue
    if len(pts) < 2:
        return build_table(tbl)          # 点太少画不出趋势，退回表格

    thr = 1.97                            # = report_helpers.BAM_THRESHOLD
    vals = [v for _, v in pts]
    lo = min(min(vals), 1.0) * 0.97
    hi = max(max(vals), thr) * 1.03
    W, H = 720, 210
    PADL, PADR, PADT, PADB = 44, 14, 14, 34
    iw, ih = W - PADL - PADR, H - PADT - PADB

    def x(i):
        return PADL + iw * i / (len(pts) - 1)

    def y(v):
        return PADT + ih * (hi - v) / (hi - lo)

    line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))
    area = f"{PADL},{PADT + ih} " + line + f" {x(len(pts) - 1):.1f},{PADT + ih}"
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{3.6 if i == len(pts) - 1 else 2.4}" '
        f'fill="{"var(--accent, #2f6f4f)" if i == len(pts) - 1 else "var(--fg, #333)"}"/>'
        for i, (_, v) in enumerate(pts))
    # x 轴标签：点多时隔一个画一个，避免糊成一片
    step = 1 if len(pts) <= 7 else 2
    xlabels = "".join(
        f'<text x="{x(i):.1f}" y="{H - 12}" text-anchor="middle" font-size="10" '
        f'fill="var(--muted, #777)">{esc(d[5:])}</text>'
        for i, (d, _) in enumerate(pts) if i % step == 0 or i == len(pts) - 1)
    ygrid = "".join(
        f'<line x1="{PADL}" y1="{y(v):.1f}" x2="{W - PADR}" y2="{y(v):.1f}" '
        f'stroke="var(--border, #ddd)" stroke-width="1"/>'
        f'<text x="{PADL - 6}" y="{y(v) + 3:.1f}" text-anchor="end" font-size="10" '
        f'fill="var(--muted, #777)">{v:.2f}</text>'
        for v in (1.0, round((1.0 + thr) / 2, 2)))
    last_d, last_v = pts[-1]
    return (
        f'<div style="overflow-x:auto">'
        f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:{W}px;height:auto" '
        f'role="img" aria-label="Deemer BAM 比值近 {len(pts)} 个交易日走势">'
        f'{ygrid}'
        # 触发阈值线
        f'<line x1="{PADL}" y1="{y(thr):.1f}" x2="{W - PADR}" y2="{y(thr):.1f}" '
        f'stroke="#c0392b" stroke-width="1.4" stroke-dasharray="5,4"/>'
        f'<text x="{W - PADR}" y="{y(thr) - 5:.1f}" text-anchor="end" font-size="10.5" '
        f'fill="#c0392b">触发线 {thr}</text>'
        f'<polygon points="{area}" fill="var(--accent, #2f6f4f)" opacity="0.10"/>'
        f'<polyline points="{line}" fill="none" stroke="var(--accent, #2f6f4f)" '
        f'stroke-width="2" stroke-linejoin="round"/>'
        f'{dots}'
        f'<text x="{x(len(pts) - 1):.1f}" y="{y(last_v) - 9:.1f}" text-anchor="end" '
        f'font-size="12" font-weight="600" fill="var(--accent, #2f6f4f)">{last_v:.2f}</text>'
        f'{xlabels}'
        f'</svg></div>'
        # 🔴 图里的 x 轴标签只有 MM-DD 且隔点显示，QA 的「字段写了却没被渲染」是拿
        #    第一行原值当文本探针的 —— 所以窗口首尾日期必须以**完整形式**出现在图注里。
        #    这不是为了骗过检查：改成图之后「这张图覆盖哪一段」本来就该写出来。
        f'<p class="src-note">窗口 {esc(pts[0][0])} → {esc(last_d)}（{len(pts)} 个交易日）·'
        f' 最新比值 <b>{last_v:.2f}</b>'
        f'（样本内第 {bam.get("pctile", "?")} 分位，窗口峰值 {bam.get("peak", "?")}）·'
        f' 口径为 10 日累计涨家数 ÷ 跌家数</p>')


def build_split_callout(text: str, sep: str = "；", label: str = "",
                        kind: str = "") -> str:
    # 🔴 2026-08-20 Vic：「哈哈你又有两个小结」——**默认标题从「小结」改成空**。
    #    同一个毛病这是第三次：7/28「删除『方法论：』这行，配色已经在说明它是什么」、
    #    8/17「其他资产里面有两个小结」、8/20 指数表和板块表的小结连着出现、
    #    而且板块表用的是四件套、**最后一条本身就叫【小结】**——同一个词出现两次。
    #    蓝色 callout 的样式已经在说「这是小结」，标题行是多余的第二层。
    #    要标题的调用点自己传 label=...，不要靠默认值。
    """按分隔符切成多段、每段悬挂缩进的callout（2026-07-27 Vic："按; 分段落；段落开头缩进对齐"）。
    整段糊成一块的长小结很难扫读——切开后每条独立一行，续行缩进与首行文字左边缘对齐。"""
    if not text:
        return ""
    # 2026-08-17 Vic：「小结里面又出现这些点点了」——截图里有空的项目符号和落单的符号。
    #    根因：写作时的段落分隔符是连续两个换行，而这里只按分隔符（默认全角分号）切。
    #    切出来的每一段**内部还带着换行**，rich() 再把它拆成多个 <p>，
    #    于是 co-item 的项目符号落在一个空行上，后面的 <p> 又各自像掉了符号的孤儿。
    #    改法：**先按作者写的换行分段**（那才是他真正的分段意图），
    #    只有单行仍然很长且含分隔符时才继续切。空段一律丢掉。
    segs = []
    for line in (x.strip() for x in text.split(chr(10))):
        if not line:
            continue
        if len(line) > 120 and sep in line:
            segs.extend(x.strip() for x in _split_outside_bold(line, sep))
        else:
            segs.append(line)
    segs = [x for x in segs if x]
    # 2026-07-27 Vic："你这分段有点多哦，但是是一句话吧，不用分段"——只有1个分号（=2段）时
    # 整体仍读作一句话，切开反而更碎。≥3段才分行，否则原样一段。
    if len(segs) <= 2:
        return build_callout(kind, text, label)
    # kind非空时走对应配色（2026-07-28 Vic：方法论不该跟「小结」同色，用绿/黄区分）
    cls = f"callout {esc(kind)}" if kind else "callout"
    # 🔴 2026-08-18 Vic：「小结还是有小点」——冒号结尾的短行是**分组小标题**，
    #    不该和条目一样挂项目符号。判据：≤24 字且以「：」结尾。
    # 🔴 2026-08-20 Vic：「蓝色部分你没改 i ii」——permission 块之前走的是 build_callout
    #    （纯段落，没有编号）。切过来之后又冒出新问题：那一块最后是**一组子项**
    #    （「不进候选的理由」下挂 4 条），如果它们也拿到 V./VI./VII./VIII.，
    #    就把「4 个并列结论 + 1 组附注」拍平成 9 条并列——**编号反而消灭了层级**。
    #    所以子项单独一档：以 · 或 - 开头 → co-sub，不参与编号、多缩进一级。
    def _cls(x):
        t = re.sub(r"\*\*", "", x).strip()
        if t[:1] in ("·", "-", "—"):
            return "co-item co-sub"
        return "co-item co-head" if (len(t) <= 24 and t.endswith("：")) else "co-item"

    def _body(x):
        t = x.strip()
        return t[1:].strip() if t[:1] in ("·", "-", "—") else t

    items = "".join(f'<div class="{_cls(x)}">{rich(_body(x))}</div>' for x in segs)
    # label="" → 不渲染标题行（2026-07-28 Vic：方法论块「删除『方法论：』这行」，配色已经在说明它是什么）
    head = f"<strong>{esc(label)}：</strong>" if label else ""
    return f'<div class="{cls}">{head}<div class="co-list">{items}</div></div>'


def build_plain_block(text: str) -> str:
    """白底陈述块——**不是小结**（2026-08-17 Vic：「D · 其他资产 里面的陈述，
    就背景白色吧，不是小结格式」）。

    蓝底 callout 在这份报告里有固定含义：**这是判断**。而「其他资产」那一段是跨资产
    读数的**陈述**（10Y 多少、金银怎么分化、TLT 在说什么），它是判断的输入不是判断本身。
    两者用同一种底色，等于告诉眼睛「这两块一样重要」。
    """
    if not text:
        return ""
    lines = [x.strip() for x in text.split(chr(10)) if x.strip()]
    if not lines:
        return ""
    items = "".join(
        '<div style="margin:0 0 6px">%s</div>' % rich(x) for x in lines)
    return ('<div style="background:var(--card,#fff);border:1px solid var(--line,#e3e8ef);'
            'border-radius:8px;padding:10px 12px;margin:8px 0">' + items + "</div>")


def build_cross_check(cc: dict) -> str:
    """三表方向一致性检查（2026-07-27 Vic："如果不同向，一定要指出"）。
    数据来自report_helpers.cross_check_alignment()。同向=淡绿低调呈现（确认而已，不抢注意力）；
    分歧=红色高亮并写明是哪一种分歧、该以哪张表为准——分歧才是这个模块存在的理由。"""
    if not cc:
        return ""
    split = cc.get("verdict") == "split"
    ZH = {"bull": "偏多", "neutral": "中性", "bear": "偏空"}
    chips = "".join(
        f'<span class="cc-chip cc-{v}">{esc(k)}：{ZH.get(v, v)}</span>'
        for k, v in (cc.get("stances") or {}).items()
    )
    cls = "cc-box cc-split" if split else "cc-box cc-aligned"
    return (f'<div class="{cls}"><div class="cc-head">{esc(cc.get("headline",""))}</div>'
            f'<div class="cc-chips">{chips}</div>'
            f'<div class="cc-detail">{rich(cc.get("detail",""))}</div></div>')




def build_catalyst_watch(t: dict) -> str:
    """催化剂在手（2026-08-20 Vic 定）。

    Vic：「我的 tradebook 里面 setup 有 momentum burst 和 ep，盘前报告是没有选这种股的…
          我买了 purr 和 coin…如果你能抓到就能大仓位进去」

    🔴 **为什么不是「burst 扫描器」**：实测 8/18 收盘时
       COIN −2.87%／量比 0.91×／收区间 4%，PURR +0.70%／量比 1.35×／收区间 63%——
       **两只在 T-1 收盘上都没有任何爆发特征**，爆发发生在 8/19 当天。
       **任何基于 T-1 收盘的形态扫描都抓不到它们**，只会在第二天告诉你昨天涨了 ＝ 追高。

    🎯 **能提前抓到的是催化剂，不是形态。**8/19 开盘前四条催化剂全都已存在：
       SEC 加密框架（8/18 盘后）· 白宫峰会（8/19 日程）·
       PURR 财报窗口已开 · 德鲁肯米勒新建仓 PURR。**后两条报告里写了，
       但写成了「持仓风险」而不是「加仓机会」。**

    所以这张表的作用是**把决定前移**：爆发那一刻他是「执行」而不是「发现」，
    仓位、入场、止损都是事前算好的——这才是「能大仓位进去」的前提。
    """
    if not t or not t.get("rows"):
        return empty_body("none", "今日没有已知催化剂在手（财报窗口 / 13F 新建仓 / "
                                  "政策日程 / X 池点名，四条都空）。")
    return build_table(t)


def build_index_panel(rows: list) -> str:
    """七只指数的唯一位置：一张 ATR 横轴图 + 一张表（2026-08-19 Vic 两条要求合并实现）。

    Vic：「voo qqq dia iwm smh rsp qqqe 表格里面好几张，你先都集中到一个地方」
        「指数闸门能用图示吗？一根横轴看位置」

    🎯 **横轴单位是 ATR，不是价格**：x = (价 − 20MA) / ATR14。
       闸门线定义就是 20MA ± 1×ATR14，所以换算之后
       **降级线恒在 −1、20MA 在 0、进攻线恒在 +1**，七只指数共用一根轴、彼此可比。
       用绝对价格画的话 VOO(705) 和 QQQE(122) 根本放不进同一张图。
    ⚠️ 闸门线只对 VOO/QQQ/IWM 画标签（框架定义），其余四只只画位置。
    """
    if not rows:
        return '<p class="placeholder">暂无数据。</p>'

    xs = [v for r in rows for v in (r.get("x_close"), r.get("x_ma50")) if v is not None]
    lo, hi = min(xs + [-1.6]), max(xs + [1.6])
    pad = max(0.45, (hi - lo) * 0.10)
    lo, hi = lo - pad, hi + pad
    W, LBL, RGT = 100.0, 8.6, 3.0          # 百分比坐标系，SVG 用 viewBox 0 0 100 H
    TRACK = W - LBL - RGT

    def px(x):
        return LBL + (x - lo) / (hi - lo) * TRACK

    ROW_H, TOP = 26.0, 20.0
    H_ = TOP + ROW_H * len(rows) + 10
    parts = [f'<svg class="idx-svg" viewBox="0 0 100 {H_:.0f}" preserveAspectRatio="xMidYMid meet" '
             f'role="img" aria-label="七只指数相对20MA的ATR位置">']

    # 三条参考线：-1 降级 / 0 20MA / +1 进攻
    for xv, lab, cls in ((-1.0, "降级线", "gl-red"), (0.0, "20MA", "gl-mid"), (1.0, "进攻线", "gl-green")):
        if not (lo <= xv <= hi):
            continue
        X = px(xv)
        parts.append(f'<line class="idx-gl {cls}" x1="{X:.2f}" y1="{TOP - 8:.0f}" '
                     f'x2="{X:.2f}" y2="{TOP + ROW_H * len(rows):.0f}"/>')
        parts.append(f'<text class="idx-gl-lab {cls}" x="{X:.2f}" y="{TOP - 11:.0f}" '
                     f'text-anchor="middle">{esc(lab)}</text>')

    for i, r in enumerate(rows):
        y = TOP + ROW_H * i + ROW_H / 2
        parts.append(f'<text class="idx-tk" x="0" y="{y + 1.6:.2f}">{esc(r["ticker"])}</text>')
        parts.append(f'<line class="idx-track" x1="{LBL:.2f}" y1="{y:.2f}" '
                     f'x2="{LBL + TRACK:.2f}" y2="{y:.2f}"/>')
        xm = r.get("x_ma50")
        if xm is not None and lo <= xm <= hi:
            X = px(xm)
            parts.append(f'<line class="idx-ma50" x1="{X:.2f}" y1="{y - 4.2:.2f}" '
                         f'x2="{X:.2f}" y2="{y + 4.2:.2f}"/>')
            parts.append(f'<text class="idx-ma50-lab" x="{X:.2f}" y="{y - 5.4:.2f}" '
                         f'text-anchor="middle">50MA</text>')
        xc = r.get("x_close")
        if xc is None:
            continue
        X = px(xc)
        cls = {"attack": "dot-green", "caution": "dot-amber",
               "broken": "dot-red"}.get(r.get("state_kind"), "dot-ref")
        parts.append(f'<circle class="idx-dot {cls}" cx="{X:.2f}" cy="{y:.2f}" r="2.6"/>')
        parts.append(f'<text class="idx-val {cls}" x="{min(X + 4.0, W - 0.5):.2f}" '
                     f'y="{y + 1.5:.2f}">{xc:+.2f}</text>')
    parts.append("</svg>")
    svg = ('<div class="idx-chart">' + "".join(parts)
           + '<div class="idx-legend">横轴 ＝ <b>(收盘 − 20MA) ÷ ATR14</b>，'
             '单位 ATR。闸门线本来就是 20MA ± 1×ATR，所以<b>进攻线恒在 +1、降级线恒在 −1</b>，'
             '七只共用一根轴、可以直接互相比。<b>闸门只对 VOO / QQQ / IWM 成立</b>，'
             '其余四只只读位置。</div></div>')

    body = []
    for r in rows:
        kd = r.get("state_kind", "ref")
        cls = {"attack": "status-met", "caution": "status-unmet",
               "broken": "status-triggered"}.get(kd, "status-unmet")
        row_cls = {"attack": "row-bull", "broken": "row-warn"}.get(kd, "")
        tr = f' class="{row_cls}"' if row_cls else ""
        gate_txt = ("%.2f / %.2f" % (r["defend"], r["attack"])) if r.get("attack") else "—"
        body.append(
            f"<tr{tr}>"
            f'<td><b>{esc(r["ticker"])}</b></td>'
            f'<td class="num">{r["close"]:.2f}</td>'
            f'<td class="num {sign_class(_RH.fpct(r.get("t1_pct")))}">{tri(_RH.fpct(r.get("t1_pct")))}</td>'
            f'<td class="num {sign_class(_RH.fpct(r.get("d5_pct")))}">{tri(_RH.fpct(r.get("d5_pct")))}</td>'
            f'<td class="num {sign_class(_RH.fpct(r.get("d21_pct")))}">{tri(_RH.fpct(r.get("d21_pct")))}</td>'
            f'<td class="num {sign_class(_rs_num(r.get("rs_1w")))}">{tri(_rs_num(r.get("rs_1w")))}</td>'
            f'<td class="num">{("%+.2f" % r["x_close"]) if r.get("x_close") is not None else "—"}</td>'
            f'<td class="num">{("%+.1f" % r["dist_ma50_atr"]) if r.get("dist_ma50_atr") is not None else "—"}</td>'
            f'<td class="num">{esc(gate_txt)}</td>'
            f'<td class="{cls}">{esc(r.get("state",""))}</td>'
            f"<td>{rich(r.get('note',''))}</td>"
            "</tr>")
    table = (
        '<table class="fixed-cols"><colgroup>'
        '<col style="width:6%"><col style="width:8%"><col style="width:7%"><col style="width:7%">'
        '<col style="width:7%"><col style="width:7%"><col style="width:8%"><col style="width:8%">'
        '<col style="width:12%"><col style="width:8%"><col style="width:22%">'
        "</colgroup><thead><tr>"
        '<th>指数</th><th class="num">收盘</th><th class="num">T-1%</th><th class="num">5日%</th>'
        '<th class="num">1月%</th><th class="num">RS(1周)</th><th class="num">距20MA(ATR)</th>'
        '<th class="num">距50MA(ATR)</th><th class="num">降级线 / 进攻线</th>'
        "<th>状态</th><th>判断</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")
    return svg + table


def _rs_num(v) -> str:
    return "-" if v is None else ("%+.1f" % v)


def build_gate_scoreboard(rows: list) -> str:
    """闸门表（2026-08-20 Vic 改版）。

    Vic：「指数闸门里面删除 dia rsp qqqe，smh 要增加进攻线和防守线，
          状态放第二栏，(=标配) 删除，距进攻/防守这两列其实不用，多给点位置给说明」

    · **只放有闸门线的四只**（VOO/QQQ/IWM/SMH）——名单在 report_helpers.GATE_TICKERS。
      DIA/RSP/QQQE 原本是闸门四列全「—」的参考行；**闸门表里放没有闸门的行本身就自相矛盾**，
      它们的读数在同节的「指数基准」RS 表和「距50MA(ATR)」表里照旧有。
    · **状态提到第二列**：它是这张表真正要回答的东西，不该排在五个数字后面。
    · **「距进攻 / 距防守」两列删掉**：收盘、进攻线、防守线三个数字并排，
      距离一眼能看出来，专门占两列去写百分比是把同一件事说第三遍——省下的宽度给「说明」。
    · **表头「进攻线(=标配)」的括号删掉**（Vic：「(=标配) 删除」）。
    """
    if not rows:
        return '<p class="placeholder">暂无数据。</p>'
    body = []
    for r in rows:
        kind = r.get("state_kind", "")
        cls = {"attack": "status-met", "caution": "status-unmet",
               "broken": "status-triggered"}.get(kind, "status-unmet")
        row_cls = {"attack": "row-bull", "broken": "row-warn"}.get(kind, "")
        tr_attr = f' class="{row_cls}"' if row_cls else ""
        body.append(
            f"<tr{tr_attr}>"
            f"<td><b>{esc(r.get('ticker',''))}</b></td>"
            f'<td class="{cls}">{esc(r.get("state",""))}</td>'
            f'<td class="num">{esc(r.get("close",""))}</td>'
            f'<td class="num">{esc(r.get("attack",""))}</td>'
            f'<td class="num">{esc(r.get("defend",""))}</td>'
            f"<td>{rich(r.get('note',''))}</td>"
            "</tr>")
    return (
        '<table class="fixed-cols"><colgroup>'
        '<col style="width:7%"><col style="width:9%"><col style="width:9%">'
        '<col style="width:9%"><col style="width:9%"><col style="width:57%">'
        "</colgroup><thead><tr>"
        '<th>指数</th><th>状态</th><th class="num">收盘</th>'
        '<th class="num">进攻线</th><th class="num">防守线</th><th>说明</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")


# 四件套标签：既认旧的【强势/可持有】方括号式，也认实际写作里更常用的「强势/可持有：」冒号式
# （2026-07-22 Vic反馈"小结不分行很难读"——查下来根因就是冒号式一直没被这个正则匹配到，
# 整段掉进build_callout糊成一块。两种写法以后都能正确分行。）
_SJT_NAMES = "强势/可持有|修复/需确认|弱势/暂避|小结"
_SIJIANTAO_RE = re.compile(r"(【(?:" + _SJT_NAMES + r")】|(?:^|(?<=[。；;\n]))\s*(?:" + _SJT_NAMES + r")[:：])")


def build_note_callouts(text: str) -> str:
    """板块类表格后的四件套note → 蓝色callout（2026-07-14 Vic再次指出：这些内容很有帮助，
    不能再用灰色小字，要放大成小结callout格式）。含四件套标签时按标签分行、标签加粗；
    无标签的普通note整段升格为蓝色callout。颜色一律蓝（7/12定案，红绿刺眼）。"""
    if not text:
        return ""
    seg = _SIJIANTAO_RE.split(text)
    if len(seg) == 1:
        return build_callout("", text)
    lead = seg[0].replace("四件套", "").strip()
    lead_html = f'<p style="margin:0 0 6px">{rich(lead)}</p>' if lead else ""
    items = []
    for i in range(1, len(seg), 2):
        label = seg[i].strip().strip("【】:：")
        body = seg[i + 1].strip().lstrip("：:").strip()
        items.append(f'<li style="margin:0 0 5px"><strong>{esc(label)}</strong>：{rich(body)}</li>')
    return (f'<div class="callout">{lead_html}'
            f'<ul style="margin:4px 0 0;padding-left:18px">{"".join(items)}</ul></div>')


def build_signal_light(sl: dict) -> str:
    """今日信号灯 → **表格**（2026-08-19 Vic：「开头信号灯很有用，但是文本这么长，
    不适合用信号灯格式，不如你改成表格」）。

    改版史（同一个问题改了三次，这次是第三次）：
      · 原版 = nowrap 的 status-tag 胶囊 → label 一长就撑成超宽单行
      · 2026-07-22 Vic：「这么长的文本，其实不适合标签，用红绿背景色块吧」→ 整块背景色行卡片
      · 2026-08-19 Vic：色块还是不对——**整块上色的背景在长文本上等于给整段话涂色，
        眼睛读不出重点**。改成表格：档位收进一个窄列（只有那一格上色），
        长文本回到正常正文，可以正常换行、正常读。

    🔴 **只认 bias / bond / dxy / breadth 四个键 + discipline**，写别的会被静默丢掉
    （8/10 写过 'vol'，整格不见）——QA 的 _signal_light_full 查这件事。
    """
    if not sl:
        return ""
    LEVEL_TXT = {"low": "低", "mid": "中", "high": "高"}
    # 2026-08-20 Vic：「只放 bias rates dxy breath ... 我不喜欢中英重复」——
    # 维度列去掉中文，只留英文键名；BOND 显示为 RATES（他的叫法）。
    order = [("BIAS", "bias"), ("RATES", "bond"),
             ("DXY", "dxy"), ("BREADTH", "breadth")]
    body = []
    for key_en, key in order:
        item = sl.get(key)
        if not item:
            continue
        level = item.get("level", "mid")
        body.append(
            f'<tr class="sig-row {esc(level)}">'
            f'<td class="sig-dim">{esc(key_en)}</td>'
            f'<td class="sig-lv {esc(level)}">{esc(LEVEL_TXT.get(level, level))}</td>'
            f'<td class="sig-txt">{rich(item.get("label", ""))}</td>'
            "</tr>")
    out = ('<table class="sig-table fixed-cols"><colgroup>'
           '<col style="width:10%"><col style="width:7%"><col style="width:83%">'
           '</colgroup><thead><tr><th>维度</th><th class="sig-lv-h">档位</th>'
           '<th>读数</th></tr></thead>'
           f'<tbody>{"".join(body)}</tbody></table>')
    disc = sl.get("discipline")
    if disc:
        # 2026-07-22 Vic：「核心纪律又有bullet point，又有**，还有红绿灯，是不是太多了」——
        # 单一强调层级：disc-item 不加 bullet。
        if isinstance(disc, list):
            lines = [rich(x) for x in disc]
        else:
            t = rich(disc)
            for mark in ("②", "③", "④", "⑤"):
                t = t.replace(mark, "␟" + mark)
            lines = [x for x in t.split("␟") if x.strip()]
        lis = "".join(f'<li class="disc-item">{x}</li>' for x in lines)
        out += ('<div class="action-directive"><span class="ad-label">核心纪律</span>'
                f'<ul class="disc-list">{lis}</ul></div>')
    return out


def build_entry_legend() -> str:
    """A级入场的bar级触发定义（2026-07-27常驻，Vic："一开始我会记不住，在A级表格下面增加注释"）。

    起因：报告长期把回踩类的入场写成"回踩9EMA企稳分批"，而"企稳"没有可判定的定义，
    Vic因此在V上找不到入场点——他等的是"贴着9EMA不破"的干净回踩，但回踩类setup的真实形态
    是"击穿后当天收回"（V 7/23：击穿-0.91%、量缩0.48×、收盘位置87%，次日再确认98%）。
    改成bar级事件后，"今天有没有触发"变成可客观判定的，不需要临场解释什么算企稳。

    🔴 2026-08-20 Vic：「这段已经失效了吧，我名字都改了」——这里一直还写着 A/B/C/D/E，
       而扫描器、表格、图例当天全部换成了 pullback / tight / spring / shakeout+burst / 2 wick。
       **改名当天没有回头查谁在引用旧名**，同一批遗留还包括 score_setup_row 的 split("+")
       和 assemble 的 count("+")（两处都当场变成恒假/恒单标签，见各自注释）。
    """
    return """<div class="entry-legend">
  <div class="el-title">入场触发一律看「bar」，不看价位</div>
  <div class="co-list">
    <div class="co-item"><b>pullback / spring —— 收回bar</b>：出现一根<b>收盘站回9EMA上方</b>且
      <b>收盘位置≥60%</b>的K线，在该bar收盘或次日开盘进；止损放该bar低点下方。
      <b>不要等「贴着均线不破」的干净回踩</b>，那种形态多数时候不会出现。</div>
    <div class="co-item"><b>tight —— 突破bar</b>：<b>收盘</b>站上突破位 且
      <b>量≥1.5×20日均量</b>才算数。<b>不要把单子挂在突破点</b>——挂单会在每一次假突破都成交，
      这正是Base Breakout实测胜率仅27%的来源。</div>
    <div class="co-item"><b>shakeout+burst</b>：等开盘后<b>第一根放量动量bar</b>，
      止损放洗盘低点下方；报告只给结构位，入场时机由盘中人工执行。</div>
    <div class="co-item"><b>2 wick</b>：<b>加分结构，不是入场形态</b>——它没有自己的触发bar，
      只在和 pullback / tight 同时出现时抬高评分（评分函数里不单独计入结构数）。</div>
    <div class="co-item"><b>通用否决</b>：<b>开盘跳空高开超过 1×ATR(14) 即视为追高</b>，当日放弃；
      触发bar量能低于0.8×20日均量视为无买盘跟进，不进。<br>
      <span class="muted">2026-08-10 Vic：「这条删了吧，要看atr的」——原来写的是固定 1.5%。
      8/7 那天 9 只跳空样本里，固定 1.5% <b>把 9 只全部否决</b>，包括当天涨 19.14% 的 WOLF
      （它的缺口只有 0.15ATR）。按 ATR 排开分界线很干净：缺口 ≥1.2ATR 的 AAOI(1.23) 和
      NET(2.14) 收盘位置只有 27% 和 15%，是全天最差的两只；≤1.0ATR 那批除 FTNT 外都收在 68% 以上。
      <b>n=9，一天的样本，不是回测结论</b>——但足以说明固定百分比在高波动票上是失效的。</span></div>
  </div>
</div>"""


def build_watchlist_a(items: list) -> str:
    """A级候选卡（2026-07-27 Vic改版）：标题只留 TICKER - 板块代码（不重复"A级"、不写中文板块名，
    "我都记得住板块代码"）；来源方法号做成chip；删掉"为什么看"三个字直接给内容；
    触发线改成**bar级触发条件**而不是一个价位（见CONTEXT.md「A级入场触发」）。"""
    if not items:
        return '<p class="placeholder">今日板块内无A级候选。</p>'
    blocks = []
    for it in items:
        src = it.get("source", "")
        chip = f'<span class="src-chip">{esc(src)}</span>' if src else ""
        rows = [f'<div class="wl-head"><strong>{esc(it.get("ticker",""))}</strong>'
                f' - {esc(it.get("sector",""))}{chip}</div>']
        if it.get("why"):
            rows.append(f'<div class="wl-line">{rich(it["why"])}</div>')
        rows.append('<div class="wl-line"><b>触发</b>：' + rich(it.get("entry", "")) + "</div>")
        rows.append('<div class="wl-line"><b>失效</b>：' + rich(str(it.get("invalid", "")))
                    + ' · <b>第一目标</b>：' + rich(str(it.get("target", ""))) + "</div>")
        if it.get("avoid_if"):
            rows.append(f'<div class="wl-line"><b>不做</b>：{rich(it["avoid_if"])}</div>')
        blocks.append(f'<div class="wl-card wl-a">{"".join(rows)}</div>')
    return "".join(blocks)


def build_watchlist_c(items: list) -> str:
    if not items:
        return ""
    lis = "".join(f'<div class="co-item">{rich(x)}</div>' for x in items)
    return f'<div class="wl-card wl-c"><div class="co-list">{lis}</div></div>'


def build_ml_leaders(leaders: list) -> str:
    """统一表格格式（替代旧的一股一框），因为名单内标的是相关的，横向对比更清楚。"""
    if not leaders:
        return '<p class="placeholder">名单为空。</p>'
    body_rows = []
    for l in leaders:
        body_rows.append(
            "<tr>"
            f"<td>{esc(l.get('ticker',''))}</td>"
            f'<td class="num">{esc(l.get("price",""))}</td>'
            f'<td class="num {sign_class(l.get("pct",""))}">{esc(l.get("pct",""))}</td>'
            f'<td class="nowrap">{esc(l.get("structure",""))}</td>'
            f'<td class="nowrap">{esc(l.get("signal","无setup"))}</td>'
            f'<td class="num">{esc(l.get("entry",""))}</td>'
            f'<td class="num">{esc(l.get("invalid",""))}</td>'
            "</tr>"
        )
    return (
        '<table class="fixed-cols"><colgroup>'
        '<col style="width:9%"><col style="width:10%"><col style="width:10%">'
        '<col style="width:14%"><col style="width:19%"><col style="width:19%">'
        '<col style="width:19%"></colgroup>'
        '<thead><tr><th>TICKER</th><th class="num">价格</th><th class="num">今日%</th>'
        "<th>结构</th><th>当日信号</th><th class=\"num\">入场点</th><th class=\"num\">失效线</th>"
        "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


def build_defensive_basket(rows: list) -> str:
    """超级避险股跟踪，与Market Leader对照：避险股被买+Leader被砸=市场risk-off，不硬做Leader。
    2026-07-21修正（Vic抓到KO盘前价填错+没显示真实跌幅）：新增"T-1收盘%"列显示真实的T-1收盘涨跌，
    这是唯一保真、随时可核对的数字；"盘前%"列在盘前时段未到/数据不可靠时留空不硬填猜测值。"""
    if not rows:
        return '<p class="placeholder">暂无数据。</p>'
    # 🔴 2026-08-17 Vic：「盘前列删除，但是 t-1 收盘你为什么不填」——两件事一起修。
    #    「盘前%」列 2026-08-12 盘前数据整体下线后就恒为 "-"，早该跟着走；
    #    而 T-1 收盘% 是这张表**唯一保真的数字**（2026-07-21 加它就是为了这个），
    #    却一直没接数据源——assemble 里 defensive_basket 只填了 ticker/price/role。
    #    现在 t1_pct 缺失直接渲染成红色「缺」，让它没法再静默空着。
    body_rows = []
    for r in rows:
        t1 = r.get("t1_pct", "")
        cell = (f'<td class="num {sign_class(t1)}">{esc(t1)}</td>' if t1
                else '<td class="num neg">缺</td>')
        body_rows.append(
            "<tr>"
            f"<td>{esc(r.get('ticker',''))}</td>"
            f'<td class="num">{esc(r.get("price",""))}</td>'
            + cell +
            f"<td>{esc(r.get('role',''))}</td>"
            "</tr>"
        )
    return (
        # 2026-08-01 与周报对齐时发现：这张表一直没有fixed-cols，列宽跟同页其它表对不齐
        '<table class="fixed-cols"><colgroup><col style="width:14%"><col style="width:16%">'
        '<col style="width:18%"><col style="width:52%"></colgroup>'
        '<thead><tr><th>TICKER</th><th class="num">收盘价</th><th class="num">T-1收盘%</th>'
        "<th>角色</th></tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


def build_recon_ledger(items: list) -> str:
    """今日对账清单：盘前只填预判+触发阈值，盘后照这张表逐条核对，解决"盘前太长记不住、盘后对不上"的问题。

    2026-08-08 增「事前概率」列（Vic 抓包 8/3–8/6 的 85% 是灌出来的，真预测只有 60%）。
    概率写下时就填，盘后不许改；纪律条目单独标灰、不进评分。约束在 helpers.validate_recon_ledger。"""
    if not items:
        return '<p class="placeholder">暂无可对账预判。</p>'
    body_rows = []
    for it in items:
        is_disc = (it.get("kind") or "market") == "discipline"
        p = it.get("prob")
        if is_disc:
            prob_cell = '<span class="prob-disc">纪律</span>'
        elif p is None:
            prob_cell = '<span class="neg">缺</span>'
        else:
            pf = float(p)
            # 越接近 0.5 越有信息量；>=0.85 是框架级防线（每份限 1 条），标出来提醒自己别滥用。
            cls = "prob-anchor" if pf >= 0.85 else "prob-live"
            prob_cell = f'<span class="{cls}">{pf * 100:.0f}%</span>'
        tr = ' class="ledger-disc"' if is_disc else ""
        body_rows.append(
            f"<tr{tr}>"
            # claim/trigger 是判断文本，走 rich()——esc() 会把 ** 渲染成字面星号
            # （2026-08-10 QA 抓到）。
            f"<td>{rich(it.get('claim',''))}</td>"
            f"<td>{rich(it.get('trigger',''))}</td>"
            f'<td style="text-align:center">{prob_cell}</td>'
            f'<td class="pending">{esc(it.get("close_check","（盘后填）"))}</td>'
            "</tr>"
        )
    # 2026-08-06 Vic：「盘后对账清单的收盘核对里面3个字就不用换行了呀」——
    # 原来没给 colgroup，浏览器把这列压到最窄导致三个字竖排。给定宽 + 表头 nowrap。
    return (
        '<table class="ledger-table fixed-cols"><colgroup>'
        '<col style="width:34%"><col style="width:30%"><col style="width:11%">'
        '<col style="width:25%"></colgroup>'
        '<thead><tr><th>今日预判</th><th>触发/阈值（可证伪）</th>'
        '<th class="nowrap" style="text-align:center">事前概率</th>'
        '<th class="nowrap">收盘核对</th></tr></thead><tbody>'
        + "".join(body_rows) + "</tbody></table>"
    )


def _x_group_by_handle(items: list, stock_mode: bool) -> str:
    """按账号归组渲染（2026-07-27 Vic：同一个账号只出现一次账号名，下面挂多条bullet）。
    每条bullet：（日期）TICKER — 内容 · 是否符合当日主线：xx（个股类才带后两段）。"""
    order, grouped = [], {}
    for it in items:
        h = it.get("handle", "")
        if h not in grouped:
            grouped[h] = []
            order.append(h)
        grouped[h].append(it)
    blocks = []
    for h in order:
        lis = []
        for it in grouped[h]:
            t = esc(it.get("time", ""))
            if stock_mode:
                tk = esc(it.get("ticker", ""))
                head = f"（{t}）{tk} — " if tk else f"（{t}）"
                tail = f' · 是否符合当日主线：{rich(it.get("aligned", "待验证"))}'
                lis.append(f'<div class="co-item">{head}{rich(it.get("note", ""))}{tail}</div>')
            else:
                lis.append(f'<div class="co-item">（{t}）{rich(it.get("summary", ""))}</div>')
        blocks.append(f'<div class="x-acct"><div class="x-handle">{esc(h)}</div>'
                      f'<div class="co-list">{"".join(lis)}</div></div>')
    return "".join(blocks)


def build_x_sentiment(macro_items: list, stock_items: list, macro_summary: str = "") -> str:
    """2026-07-27 Vic再改：宏观类不再用蓝色小结整段（"很难读"），改成跟个股类同一套
    「账号名 + 该账号多条bullet」格式；个股类标题改「个股类」。"""
    parts = ["<h3>宏观类</h3>"]
    if macro_items:
        parts.append(_x_group_by_handle(macro_items, stock_mode=False))
        # 2026-08-05修：原本 macro_summary 只在「没有宏观帖」时当兜底显示，
        # 而实际每天都有帖子，所以那段综合判断从来没渲染出来过（QA新检查抓到）。
        # 它是判断层写的东西，比帖子列表本身更该被看见——改成跟在列表后面照常渲染。
        if macro_summary:
            parts.append(build_split_callout(macro_summary))
    elif macro_summary:
        parts.append(build_split_callout(macro_summary))
    else:
        parts.append('<p class="placeholder">今日无实质交易相关内容。</p>')
    parts.append("<h3>个股类</h3>")
    if stock_items:
        parts.append(_x_group_by_handle(stock_items, stock_mode=True))
    else:
        parts.append('<p class="placeholder">今日无实质交易相关内容。</p>')
    return "".join(parts)


# 日历图标（2026-08-20 Vic：「圆点干脆改成 emoji 吧，区分个股宏观，或者重要不重要？
# **不要都用箭靶**」）。原来 li::before 是统一的「·」，重要性靠手写 🎯 —— 结果
# 一格里四条有三条挂 🎯，等于没标（同「铺满 = 等于没标」那条）。
#
# 拆成两个正交维度，各管各的：
#   **类型** → 图标（这里出）        **重要** → 字重＋左侧色条（CSS 出，不再占一个 emoji）
CAL_ICON = {
    "fed":    "🏛️",   # 🏛 央行 / 财政 / 白宫 / 官员讲话
    "data":   "📊",          # 📊 经济数据（初请 / PMI / 成屋销售）
    "stock":  "🏢",          # 🏢 个股 · 公司事件（财报 / 批文 / 上市）
    "market": "📈",          # 📈 指数 · 板块 · 跨资产
}
CAL_KIND_CN = {"fed": "央行政策", "data": "经济数据",
               "stock": "个股公司", "market": "指数板块"}
# 关键词兜底：历史草稿里的事件是纯字符串，没有类型标注。**显式标注永远优先**，
# 这张表只在没标注时用，规则写在这里是为了能被 QA 和肉眼一起检查。
_CAL_KW = (
    ("fed",    ("FOMC", "纪要", "Fed", "美联储", "财政部", "白宫", "Trump", "特朗普",
                "Jackson Hole", "主席", "讲话", "演讲", "降息", "加息", "国债", "回购")),
    ("data",   ("初请", "失业", "PMI", "CPI", "PPI", "非农", "零售", "成屋", "耐用品",
                "GDP", "PCE", "消费者信心", "库存")),
    ("market", ("SPX", "QQQ", "SMH", "IWM", "VOO", "指数", "板块", "半导体", "BTC",
                "黄金", "原油", "美元", "DXY")),
)


def _cal_kind(text: str) -> str:
    for kind, kws in _CAL_KW:
        if any(k in text for k in kws):
            return kind
    return "stock"          # 剩下的默认当个股（多数是公司事件）


def _cal_item(x):
    """接受三种写法，越靠前优先级越高：
         {"k": "fed", "t": "FOMC 纪要 …", "hot": True}
         "[fed] FOMC 纪要 …"
         "FOMC 纪要 …"                      ← 关键词兜底
    """
    hot = False
    if isinstance(x, dict):
        kind, text, hot = x.get("k"), x.get("t", ""), bool(x.get("hot"))
    else:
        kind, text = None, str(x)
        if text.startswith("[") and "]" in text[:12]:
            kind, text = text[1:text.index("]")].strip(), text[text.index("]") + 1:].strip()
    # 🔴 手写的 🎯 / 🔴 在这里剥掉：重要性改由 hot 表达，emoji 不再兼职
    for mark in ("🎯", "🔴"):
        while mark in text:
            hot = True
            text = text.replace(mark, "", 1).strip()
    if kind not in CAL_ICON:
        kind = _cal_kind(text)
    return kind, text, hot


def build_week_calendar(cal: dict) -> str:
    """本周大事日历（2026-07-27 Vic："做成6列 5个工作日 加周末的日历样子"）。
    cal = {"headers": ["周一 7/27", ...6个], "cells": [[...], ...]}，每格是该日事件列表。
    每条事件的写法见 _cal_item。"""
    if not cal or not cal.get("headers"):
        return ""
    ths = "".join(f"<th>{esc(h)}</th>" for h in cal["headers"])
    tds = []
    used = set()
    for col in cal.get("cells", []):
        lis = []
        for x in col or []:
            kind, text, hot = _cal_item(x)
            used.add(kind)
            lis.append(
                f'<li class="cal-i{" hot" if hot else ""}">'
                f'<span class="cal-ic" title="{esc(CAL_KIND_CN[kind])}">{CAL_ICON[kind]}</span>'
                f'{rich(text)}</li>')
        items = "".join(lis)
        tds.append(f'<td>{f"<ul class=cal-list>{items}</ul>" if items else "<span class=cal-none>—</span>"}</td>')
    legend = "".join(
        f'<span class="cal-lg"><i>{CAL_ICON[k]}</i>{esc(CAL_KIND_CN[k])}</span>'
        for k in ("fed", "data", "stock", "market") if k in used)
    return (f'<table class="cal-table"><thead><tr>{ths}</tr></thead>'
            f"<tbody><tr>{''.join(tds)}</tr></tbody></table>"
            f'<div class="cal-legend">{legend}'
            '<span class="cal-lg cal-lg-hot"><i></i>加粗＝重要</span></div>')


RESULT_BADGE_CLASS = {
    "hit": "result-hit", "partial": "result-partial", "miss": "result-miss",
    "not_triggered": "result-not-triggered", "unplanned": "result-partial",
}
RESULT_BADGE_LABEL = {
    "hit": "命中", "partial": "部分", "miss": "失误",
    "not_triggered": "未触发", "unplanned": "计划外",
}


def _stacked_bar(a: int, b: int, c: int) -> str:
    total = a + b + c
    if total == 0:
        return ""
    a_pct, b_pct, c_pct = a / total * 100, b / total * 100, c / total * 100
    return (
        f'<div class="hitbar" role="img" aria-label="{a}/{b}/{c}">'
        f'<i class="h" style="width:{a_pct:.1f}%"></i>'
        f'<i class="p" style="width:{b_pct:.1f}%"></i>'
        f'<i class="m" style="width:{c_pct:.1f}%"></i></div>'
    )


def build_hitbar(hit: int, partial: int, miss: int) -> str:
    bar = _stacked_bar(hit, partial, miss)
    if not bar:
        return ""
    legend = (
        f'<div class="hitbar-legend">盘前判断对账：'
        f'<span class="dot h"></span><b>{hit}</b> 命中'
        f'<span class="dot p"></span><b>{partial}</b> 部分'
        f'<span class="dot m"></span><b>{miss}</b> 失误</div>'
    )
    return bar + legend


def build_risk_summary_bar(low_n: int, mid_n: int, high_n: int) -> str:
    bar = _stacked_bar(low_n, mid_n, high_n)
    if not bar:
        return ""
    legend = (
        f'<div class="hitbar-legend">总体：'
        f'<span class="dot h"></span><b>{low_n}</b> 低'
        f'<span class="dot p"></span><b>{mid_n}</b> 中'
        f'<span class="dot m"></span><b>{high_n}</b> 高</div>'
    )
    return bar + legend


# 2026-07-28 Vic：「背景不要颜色了，只需要对账的标签颜色」——整行染色退役，
# 严重度只由「对账」列的result徽章表达，一行只有一个着色点。
RECON_ROW_CLASS = {}


def build_recon_table(rows: list) -> str:
    """2026-07-15 Vic："标签页添加背景颜色，好的绿色，不好的红色"——整行染色（跟scoreboard_table
    同一套语言），不只是小徽章淡淡一圈色。hit=绿整行；miss/unplanned=红整行（计划外建仓本质是违反
    纪律，归为"不好"而不是中性的partial）；partial/not_triggered=不整行染色，只留徽章区分。"""
    if not rows:
        return '<p class="placeholder">暂无对账记录。</p>'
    body_rows = []
    for r in rows:
        result = r.get("result", "not_triggered")
        badge_cls = RESULT_BADGE_CLASS.get(result, "result-not-triggered")
        badge_label = RESULT_BADGE_LABEL.get(result, "未触发")
        row_cls = RECON_ROW_CLASS.get(result, "")
        is_disc = (r.get("kind") or "market") == "discipline"
        if is_disc:
            row_cls = (row_cls + " ledger-disc").strip()
        tr_attr = f' class="{row_cls}"' if row_cls else ""
        # 事前概率 + 该条的 Brier 贡献：猜确定的事猜中几乎不加分，猜错则重罚。
        p, brier_cell = r.get("prob"), "—"
        if is_disc:
            prob_cell = '<span class="prob-disc">纪律</span>'
        elif p is None:
            prob_cell = '<span class="neg">缺</span>'
        else:
            pf = float(p)
            prob_cell = (f'<span class="{"prob-anchor" if pf >= 0.85 else "prob-live"}">'
                         f'{pf * 100:.0f}%</span>')
            out = _RH.RECON_OUTCOME.get(result)
            if out is not None:
                b = (pf - out) ** 2
                brier_cell = f'<span class="brier-val {"pos" if b < 0.15 else "neg"}">{b:.3f}</span>'
        body_rows.append(
            f"<tr{tr_attr}>"
            f"<td>{rich(r.get('plan',''))}</td>"
            f"<td>{rich(r.get('actual',''))}</td>"
            f'<td style="text-align:center">{prob_cell}</td>'
            f'<td style="text-align:center"><span class="result-badge {badge_cls}">{badge_label}</span></td>'

            f"<td>{rich(r.get('fix',''))}</td>"
            "</tr>"
        )
    return (
        '<table class="recon-table fixed-cols"><colgroup>'
        # 🔴 2026-08-17 Vic：「brier score 就放周报吧」——**整列删掉**，
        #    一整列日频 Brier 和那一行小字是同一件事。「事前」列（概率）保留：
        #    它是这条预判有多难的读数，不是打分。
        '<col style="width:27%"><col style="width:27%"><col style="width:10%">'
        '<col style="width:10%"><col style="width:26%"></colgroup>'
        '<thead><tr>'
        "<th>盘前</th><th>收盘实况</th>"
        '<th class="nowrap" style="text-align:center">事前</th>'
        '<th style="text-align:center">对账</th><th>下次修正</th>'
        "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


ITER_KIND_CLASS = {
    "good": "it-good", "bad": "it-bad", "pattern": "it-pattern",
    "keep": "it-good", "adjust": "it-adjust", "fix": "it-bad", "reverse": "it-pattern",
}


def _iterations_from_legacy(lessons: dict, corrections: list) -> list:
    """旧数据（lessons三段 + corrections独立表）自动折进新结构，保证只有一种画法。
    2026-07-28 Vic：「修正规则的新规则可以放在本日迭代表格的右边，可以左右对比看」——
    合表之后就不该再存在第二种渲染路径，否则又是一条会漂回去的路（参考A/B/C那次）。"""
    rows = []
    for kind in ("good", "bad", "pattern"):
        for x in (lessons or {}).get(kind, []):
            rows.append({"kind": kind, "lesson": x, "rule": ""})
    for c in corrections or []:
        rows.append({"kind": c.get("status", "keep"),
                     "lesson": c.get("before", ""),
                     "rule": c.get("after") or c.get("text", "")})
    return rows


def build_iterations(rows: list) -> str:
    """本日迭代（2026-07-28 Vic改版）：左边写观察到什么、右边写因此改了哪条规则，左右对比。
    整表白底不染色（Vic：「也不要颜色，就标签颜色有」）；类别只靠最左那道细色条表达，
    不写「对/错/形态」字样（Vic 前一轮：「对错形态字删了，有红绿了」）。"""
    if not rows:
        return ""
    trs = []
    for r in rows:
        cls = ITER_KIND_CLASS.get(r.get("kind", "pattern"), "it-pattern")
        rule = r.get("rule", "")
        trs.append(
            f'<tr><td class="it-bar {cls}"></td>'
            f'<td class="it-lesson">{rich(r.get("lesson", ""))}</td>'
            f'<td class="it-rule">{rich(rule) if rule else "<span class=it-none>—</span>"}</td></tr>'
        )
    return ('<table class="iter-table"><thead><tr><th></th>'
            "<th>本日迭代</th><th>修正规则（新）</th></tr></thead>"
            f'<tbody>{"".join(trs)}</tbody></table>')




def build_tradebook_block(text: str) -> str:
    if not text:
        return '<p class="placeholder">待生成。</p>'
    return f'<div class="panel" style="padding:14px 16px;white-space:pre-wrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;">{esc(text)}</div>'


def build_ml_leaders_postmarket(rows: list) -> str:
    if not rows:
        return '<p class="placeholder">暂无数据。</p>'
    body_rows = []
    for r in rows:
        behavior = r.get("behavior_ok", "")
        mark = {"yes": "✅ 符合", "so-so": "⚠️ 一般", "no": "❌ 不符合"}.get(behavior, behavior)
        body_rows.append(
            "<tr>"
            f"<td>{esc(r.get('ticker',''))}</td>"
            f'<td class="num {sign_class(r.get("pct",""))}">{esc(r.get("pct",""))}</td>'
            f'<td class="num {sign_class(r.get("qqq_pct",""))}">{esc(r.get("qqq_pct",""))}</td>'
            f'<td class="num {sign_class(r.get("excess",""))}">{esc(r.get("excess",""))}</td>'
            f'<td class="nowrap">{esc(r.get("regime",""))}</td>'
            f'<td class="nowrap">{esc(mark)}</td>'
            # 2026-08-11：这两列会写整段判断文字，必须走 rich()，否则 ** 变字面星号
            # （CONTEXT「会写整段判断文字的字段一律用 rich()」）。ML Leader 名单 7/17–8/07 是空的，
            # 这张表从没真渲染过，所以这个缺陷到 8/10 名单恢复三只时才第一次暴露。
            f"<td>{rich(r.get('setup_triggered',''))}</td>"
            f"<td>{rich(r.get('structure_change',''))}</td>"
            "</tr>"
        )
    # 同日补 colgroup + table_class：QA「表格列宽对齐」要求每张表都有，手写 HTML 的表最容易漏
    return (
        '<table class="fixed-cols"><colgroup>'
        '<col style="width:9%"><col style="width:9%"><col style="width:10%"><col style="width:9%">'
        '<col style="width:12%"><col style="width:10%"><col style="width:17%"><col style="width:24%">'
        "</colgroup>"
        '<thead><tr><th>TICKER</th><th class="num">今日%</th><th class="num">QQQ今日%</th>'
        '<th class="num">超额</th><th>大盘性质</th><th>领袖行为</th><th>Setup触发</th><th>结构变化</th>'
        "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


def build_key_takeaways(items: list) -> str:
    """2026-07-12 Vic二次修正：核心结论=一整块蓝色callout（内部逐条列表），
    不要每条一个蓝块（"很散乱的"）。
    2026-07-27改版对标老师报告的「核心結論」格式（Vic确认要）：编号1./2./3.（有优先级顺序，
    不是并列所以不用bullet）+ 每条**粗体标题句**起头、后面才是1-2句支撑。
    写法：item用"标题句。|支撑句"，用竖线分隔；没有竖线则整条当标题句。"""
    if not items:
        return ""
    lis = []
    for x in items:
        head, _, body = str(x).partition("|")
        body_html = f'<div class="kt-body">{rich(body.strip())}</div>' if body.strip() else ""
        lis.append(f'<li class="kt-item"><span class="kt-head">{rich(head.strip())}</span>{body_html}</li>')
    # 2026-07-28 Vic：「KEY TAKEAWAYS 字我记得删除了，这段字体也不一样，改成和核心纪律一样的黄色」
    # ——所在section的h2已经是「今日定位」，块内再写一次英文标题是重复；蓝callout也让它跟
    # 核心纪律看着像两种东西。改成同一个action-directive黄块，不带label。
    return ('<div class="action-directive">'
            f'<ol class="kt-list">{"".join(lis)}</ol></div>')


def build_action_directive(primary: list, watch: list, avoid: list, invalidate: str) -> str:
    if not (primary or watch or avoid or invalidate):
        return ""
    lis = []
    for x in primary or []:
        lis.append(f'<li class="ad-primary">{rich(x)}</li>')
    for x in watch or []:
        lis.append(f'<li class="ad-watch">{rich(x)}</li>')
    for x in avoid or []:
        lis.append(f'<li class="ad-avoid">{rich(x)}</li>')
    if invalidate:
        lis.append(f'<li class="ad-invalidate"><strong>反向信号：</strong>{rich(invalidate)}</li>')
    return (
        '<div class="action-directive"><span class="ad-label">今日定位</span>'
        f'<ul class="ad-list">{"".join(lis)}</ul></div>'
    )


def build_squeeze_table(rows: list) -> str:
    """轧空候选：FINRA做空比例/Days to Cover + FINRA每日做空成交量 + iborrowdesk借券费率三源拼出。"""
    if not rows:
        return '<p class="placeholder">今日无标的触发或接近轧空门槛（做空比例>20% + 借券费率明显偏高 + 有催化剂）。</p>'
    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{esc(r.get('ticker',''))}</td>"
            f'<td class="num">{esc(r.get("short_pct_float",""))}</td>'
            f'<td class="num">{esc(r.get("days_to_cover",""))}</td>'
            f'<td class="num">{esc(r.get("borrow_fee",""))}</td>'
            f"<td>{rich(r.get('short_volume_trend',''))}</td>"
            f"<td>{rich(r.get('catalyst',''))}</td>"
            f"<td>{rich(r.get('status',''))}</td>"
            "</tr>"
        )
    # 2026-08-10：这张表是手写 HTML，此前既没 table_class 也没 colgroup，
    # QA「表格列宽对齐」一直红着。补上，跟 build_table 的输出对齐。
    return (
        '<table class="fixed-cols"><colgroup>'
        '<col style="width:8%"><col style="width:11%"><col style="width:11%">'
        '<col style="width:10%"><col style="width:14%"><col style="width:22%">'
        '<col style="width:24%"></colgroup>'
        '<thead><tr><th>TICKER</th><th class="num">做空比例/DTC</th>'
        '<th class="num">Days to Cover</th><th class="num">借券费率</th>'
        "<th>近期做空成交趋势</th><th>催化剂</th><th>触发状态</th>"
        "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


def build_event_gap_table(rows: list) -> str:
    """事件缺口延续候选（2026-08-05 Vic 定的独立品类，**不进 A/B/C**）。

    Vic 原话：「可以追高，只要是有催化和叙事，半仓，10% 止损就可以」。
    起因：8/4 LDOS 的财报缺口涨幅被算进了 A 级 setup 战绩（虚账），
    而同日 PLTR +29.45% 被扫描命中却因「没有结构止损可用」被丢掉——A/B/C 装不下这一类。
    回测见 CONTEXT.md 同名章节：10% 止损位合理、半仓必须、避开≥15%的极端缺口。
    """
    if not rows:
        return '<p class="placeholder">今日无事件缺口候选（需同时具备：一级信源核实的催化 + 属于当前主线的叙事）。</p>'
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td><b>{esc(r.get('ticker',''))}</b></td>"
            f"<td>{rich(r.get('catalyst',''))}</td>"
            f"<td>{rich(r.get('narrative',''))}</td>"
            f'<td class="num">{rich(r.get("gap_pct",""))}</td>'
            f'<td class="ctr">{esc(r.get("extreme",""))}</td>'
            f'<td class="ctr">{esc(r.get("size",""))}</td>'
            f'<td class="ctr">{esc(r.get("stop",""))}</td>'
            f"<td>{rich(r.get('note',''))}</td>"
            "</tr>")
    return ('<table class="fixed-cols"><colgroup>'
            '<col style="width:7%"><col style="width:24%"><col style="width:13%">'
            '<col style="width:8%"><col style="width:7%"><col style="width:6%">'
            '<col style="width:8%"><col style="width:27%"></colgroup>'
            '<thead><tr><th>TICKER</th><th>催化（须一级信源）</th><th>叙事/主线</th>'
            '<th class="num">缺口幅度</th><th class="ctr">≥15%?</th><th class="ctr">仓位</th>'
            '<th class="ctr">止损</th><th>备注</th></tr></thead><tbody>'
            + "".join(body) + "</tbody></table>")


def build_13dg_table(rows: list) -> str:
    """SEC 13D/13G 大额持仓变动，只列与Vic持仓/Leader/Watchlist相关的filer。"""
    if not rows:
        return empty_body("none", "EDGAR getcurrent 已查（13D / 13G 各一次），无相关标的的新申报。")
    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{esc(r.get('ticker',''))}</td>"
            f"<td>{esc(r.get('filer',''))}</td>"
            f"<td>{esc(r.get('form',''))}</td>"
            f"<td>{esc(r.get('filed_date',''))}</td>"
            f"<td>{rich(r.get('note',''))}</td>"
            "</tr>"
        )
    # 2026-08-17：这张表此前是裸 <table>（QA「表格列宽对齐」抓到最后一张）。
    # 之前一直空着没人发现——真扫出行来的第一天就露了。
    return (
        '<table class="fixed-cols"><colgroup><col style="width:9%"><col style="width:20%">'
        '<col style="width:9%"><col style="width:11%"><col style="width:51%"></colgroup>'
        '<thead><tr><th>标的</th><th>申报人/机构</th><th>类型</th><th>申报日期</th>'
        "<th>解读</th></tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


VOL_TAG_BADGE = {"高": "badge green", "低": "badge red",
                 "放量": "badge green", "低量·谨慎": "badge red"}  # 后两个留作旧数据兼容


def build_dispersion(d: dict) -> str:
    """A · 离散度（2026-08-06 建；**2026-08-10 重做可读性**）。

    Vic 2026-08-10：「这个表格我不会读」。原来只给四个数字（比值 / 标准差 / 指数涨跌 /
    COR1M），没有一句话说这些数字意味着什么、今天该怎么做。四个数字里有三个是中间量，
    只有「档位」是结论——但档位被放在最下面一行小字里。

    重做：**先给一句人话，再给刻度条，最后才是原始数字**。
    比值 = 板块横截面标准差 ÷ |指数当日涨跌|。<1.5 指数主导 / 1.5-3 混合 / >3 选股主导。
    """
    if not d or d.get("ratio") is None:
        return '<p class="placeholder">暂无离散度读数。</p>'
    r = d["ratio"]
    regime = d.get("regime", "")
    kind = {"指数主导": "green", "混合": "blue", "选股主导": "amber"}.get(regime, "blue")

    # ① 一句人话：把三个中间量翻译成「今天发生了什么」
    if r < 1.5:
        plain = ("**板块之间几乎没有分化。** 十一个板块的收益挤在一条窄带里"
                 "（横截面标准差 %.2f），而指数自己动了 %.2f%%——"
                 "**板块的差异比指数的动作还小。**" % (d["sd"], d["idx_move"]))
        todo = ["**这种环境里，挑对板块赚不到多少超额收益，跟着指数走的性价比更高。**",
                "**闸门 / 广度 / VIX 这类市场级信号现在是可用的**——"
                "在「选股主导」档里它们的信息量极低。"]
    elif r <= 3:
        plain = ("**板块分化中等。** 横截面标准差 %.2f，指数动了 %.2f%%——"
                 "既不是齐涨齐跌，也没有极端分化。" % (d["sd"], d["idx_move"]))
        todo = ["**市场级信号和个股选择都只有一半权重。**",
                "板块内部的强弱开始有意义，但还不到「指数怎么走无所谓」的程度。"]
    else:
        plain = ("**板块之间在剧烈分化。** 横截面标准差 %.2f 远大于指数的 %.2f%%——"
                 "**指数今天走多少，跟你手里的票走多少几乎没关系。**" % (d["sd"], d["idx_move"]))
        todo = ["🔴**这种环境里用闸门 / VIX 判风险是失效的**——"
                "指数波动率量不到个股波动率（8/6 就是：个股跌 13~20%，VIX 反而更低）。",
                "**该看的是持仓的单票波动和止损距离。**"]

    # ② 刻度条：三档 + 今天的位置
    pos = min(max(r / 4.5, 0.0), 1.0) * 100
    scale = (
        '<div class="disp-scale">'
        '<div class="disp-bar">'
        '<i class="seg s-idx" style="width:33.3%"></i>'
        '<i class="seg s-mix" style="width:33.3%"></i>'
        '<i class="seg s-stk" style="width:33.4%"></i>'
        f'<b class="disp-pin" style="left:{pos:.1f}%"></b>'
        '</div>'
        '<div class="disp-ticks"><span>指数主导 &lt;1.5</span>'
        '<span>混合 1.5–3</span><span>选股主导 &gt;3</span></div>'
        '</div>')

    # ③ 原始数字放最后，供核对
    cells = [
        ("今天的比值", "%.2f" % r, "一年 %d 分位（中位 %.2f）"
         % (d.get("ratio_pctile", 0), d.get("ratio_median_1y", 0))),
        ("板块横截面标准差", "%.2f" % d["sd"], "一年 %d 分位 · 中位 %.2f"
         % (d.get("sd_pctile", 0), d.get("sd_median_1y", 0))),
        ("指数当日涨跌", "%.2f%%" % d["idx_move"], "比值的分母"),
        ("隐含相关性 COR1M", ("%.2f" % d["cor1m"]) if d.get("cor1m") else "—",
         ("COR3M %.2f · 越低=个股越各走各的" % d["cor3m"]) if d.get("cor3m") else "越低=离散度越高"),
    ]
    tds = "".join(
        f'<td><div class="sub">{esc(k)}</div><div class="big">{esc(v)}</div>'
        f'<div class="sub">{esc(x)}</div></td>' for k, v, x in cells)

    return (f'<div class="callout co-{kind}"><strong>{esc(regime)}（比值 {r:.2f}）</strong>'
            f'<div class="co-list"><div class="co-item">{rich(plain)}</div>'
            + "".join(f'<div class="co-item">{rich(x)}</div>' for x in todo)
            + '</div></div>'
            + scale
            + f'<table class="fixed-cols"><tbody><tr>{tds}</tr></tbody></table>')


def build_gate_etf_table(t: dict) -> str:
    """03 指数闸门表（2026-08-06 Vic 三条改造）。

    ①「（盘前 x%）」从 T-1% 格里拆出来，另起一行显示（原来挤在同一格里换行很难读）
    ②表头去掉解释性括号：「进攻线(+1ATR)」→「进攻线」、「谨慎线(20MA)」→「谨慎线」、
      「降级线(-1ATR)」→「降级线」
    ③收盘价站上进攻线 → 进攻线那格标绿；跌破降级线 → 降级线那格标红。
      判定用数值比较，不靠文字。
    """
    rows = t.get("rows") or []
    if not rows:
        return '<p class="placeholder">暂无数据。</p>'
    hdr = ["ETF", "收盘价", "T-1%", "进攻线", "谨慎线", "降级线", "50MA", "距50MA", "判断"]

    def num(x):
        try:
            return float(str(x).replace("%", "").replace("+", "").replace(",", ""))
        except Exception:
            return None

    body = []
    for r in rows:
        r = list(r) + [""] * (9 - len(r))
        close = num(r[1])
        atk, dfd = num(r[3]), num(r[5])
        # T-1% 里可能带「（盘前x%）」，拆成两行
        t1 = str(r[2])
        pre = ""
        if "（盘前" in t1:
            t1, pre = t1.split("（盘前", 1)
            pre = "盘前" + pre.rstrip("）")
        t1_cell = f'{esc(t1)}<div class="sub">{esc(pre)}</div>' if pre else esc(t1)
        atk_cls = "num up" if (close is not None and atk is not None and close >= atk) else "num"
        dfd_cls = "num dn" if (close is not None and dfd is not None and close <= dfd) else "num"
        body.append(
            "<tr>"
            f"<td><b>{esc(r[0])}</b></td>"
            f'<td class="num">{esc(r[1])}</td>'
            f'<td class="num {sign_class(t1)}">{t1_cell}</td>'
            f'<td class="{atk_cls}">{esc(r[3])}</td>'
            f'<td class="num">{esc(r[4])}</td>'
            f'<td class="{dfd_cls}">{esc(r[5])}</td>'
            f'<td class="num">{esc(r[6])}</td>'
            f'<td class="num {sign_class(r[7])}">{esc(r[7])}</td>'
            f"<td>{rich(r[8])}</td>"
            "</tr>")
    cols = ["8%", "10%", "11%", "11%", "11%", "11%", "9%", "9%", "20%"]
    return ('<table class="fixed-cols"><colgroup>'
            + "".join(f'<col style="width:{w}">' for w in cols) + "</colgroup><thead><tr>"
            + "".join(f'<th class="num">{h}</th>' if i in (1, 2, 3, 4, 5, 6, 7) else f"<th>{h}</th>"
                      for i, h in enumerate(hdr))
            + "</tr></thead><tbody>" + "".join(body) + "</tbody></table>")


def build_premarket_movers(rows: list) -> str:
    """2026-07-15 Vic要求：加'盘前量'和'量能'两列，区分是大量涨还是量很低（低量的move更可能是
    小单打出来的虚高%，不能同等看待）。vol_tag取值'放量'/'低量·谨慎'/'-'，前两者渲染成badge。
    2026-07-22 Vic："Premarket Movers 价格删除，给多点空间"——价格列去掉，省下的宽度让
    催化/read-through/交易判断三个长文本列能舒展。绝对价格在别的表里都有，这张表看的是变化不是价位。"""
    if not rows:
        return '<p class="placeholder">今日无重大盘前异动。</p>'
    body_rows = []
    for r in rows:
        tag = r.get("vol_tag", "-")
        tag_html = f'<span class="{VOL_TAG_BADGE[tag]}">{esc(tag)}</span>' if tag in VOL_TAG_BADGE else esc(tag)
        body_rows.append(
            "<tr>"
            f"<td>{esc(r.get('ticker',''))}</td>"
            f'<td class="num {sign_class(r.get("pct",""))}">{esc(r.get("pct",""))}</td>'
            f'<td class="num">{esc(r.get("pm_vol",""))}</td>'
            f"<td>{tag_html}</td>"
            f"<td>{rich(r.get('catalyst',''))}</td>"
            f"<td>{rich(r.get('sector_readthrough',''))}</td>"
            f"<td>{rich(r.get('judgment',''))}</td>"
            "</tr>"
        )
    return (
        '<table class="movers fixed-cols"><colgroup>'
        '<col style="width:8%"><col style="width:10%"><col style="width:9%">'
        '<col style="width:8%"><col style="width:25%"><col style="width:16%">'
        '<col style="width:24%"></colgroup>'
        '<thead><tr><th>股票</th><th class="num">盘前变化</th>'
        '<th class="num">盘前量</th><th>量能</th>'
        "<th>催化/成交确认</th><th>板块read-through</th><th>交易判断</th>"
        "</tr></thead><tbody>" + "".join(body_rows) + "</tbody></table>"
    )


def build_playbook_scenarios(scenarios: list) -> str:
    """2026-07-08起每个情景必须带prob（主观发生概率%，三情景合计100），盘后对账时校准。"""
    if not scenarios:
        return ""
    blocks = []
    for s in scenarios:
        prob = s.get("prob")
        prob_html = ""
        if prob is not None:
            bar_w = min(100, max(0, int(prob)))
            prob_html = (
                f'<span style="float:right;font-weight:800;font-size:15px">{esc(prob)}%</span>'
                f'<div style="height:6px;background:#eceef1;border-radius:999px;margin:6px 0 8px">'
                f'<div style="height:6px;width:{bar_w}%;background:var(--blue);border-radius:999px"></div></div>'
            )
        blocks.append(
            f"""<div class="callout">
  <strong>{rich(s.get("title",""))}</strong>{prob_html}
  触发：{rich(s.get("trigger",""))}<br>
  执行：{rich(s.get("action",""))}<br>
  目标/等待：{rich(s.get("target",""))}
</div>"""
        )
    return "".join(blocks)


def section(anchor: str, title: str, body: str) -> str:
    return f'<section id="{esc(anchor)}"><h2>{esc(title)}</h2>{body}</section>'


def placeholder_section(anchor: str, title: str, text: str) -> str:
    return section(anchor, title, f'<p class="placeholder">{esc(text)}</p>')


# =========================================================================
# 空节三态（2026-08-07 Vic：「如果哪个板块没有扫出来，你不要空着，
# 你放"无"这样就不会漏掉」）。
#
# 做成三态而不是一个"无"——因为这三件事对决策的含义完全相反：
#   · 无     = 跑了、结果为空          → 今天真的没有候选，可以安心跳过
#   · 暂停   = 主动 park，不跑          → 是个决定，不是市场信息
#   · 数据缺 = 想跑但数据源不可用      → **不知道有没有**，这才是真正的风险
# 三种都写"无"的话，「数据缺」会被读成「扫了没有」——那还是漏掉了。
#
# 关键：**空节也必须渲染**。今天已经出过两次事故（FTD 暂停→整个「02 市场广度」
# 连同 note 静默消失；A 级为空→Setup A 专项对账整节消失），根因都是
# 「内容为空 → 整节不 append」。标题永远在、状态永远显式，漏不掉。
EMPTY_STATES = {
    "none":   ("无", "es-none"),
    "parked": ("暂停", "es-parked"),
    "nodata": ("数据缺", "es-nodata"),
}


def empty_body(state: str, note: str = "") -> str:
    """空内容的统一渲染体（可嵌在节里，也可单独成节）。"""
    label, cls = EMPTY_STATES.get(state, EMPTY_STATES["none"])
    out = f'<p class="empty-state"><span class="empty-tag {cls}">{esc(label)}</span>'
    if note:
        out += f'<span class="empty-note">{rich(note)}</span>'
    return out + "</p>"


def empty_section(anchor: str, title: str, state: str, note: str = "") -> str:
    return section(anchor, title, empty_body(state, note))


def section_or_empty(anchor: str, title: str, body: str, state: str, note: str = "") -> str:
    """有内容就正常渲染，没内容就渲染三态标记——调用方不需要再写 if。"""
    return section(anchor, title, body if body else empty_body(state, note))


def build_toc(sections: list) -> str:
    links = "".join(f'<a href="#{esc(a)}">{esc(t)}</a>' for a, t in sections)
    return f'<nav class="toc" aria-label="章节导航">{links}</nav>'



# 🔴 盘前小节顺序的**唯一**真源（2026-08-19 建）。
#    在此之前顺序 = 各 body_sections.append() 的书写位置，散在 500 行里，
#    调一次顺序要在四五个地方来回找。现在统一在 render_premarket 末尾按 id 重排。
#    没列进来的 id 保持相对次序、排在列出的之后。
PREMARKET_SECTION_ORDER = [
    "signal",        # 今日信号灯
    "gate",          # 03 指数闸门 ← 2026-08-19 从第 7 位提到这里
    "risk",          # 今日动能打分
    "breadthscore",  # 市宽打分（三表一致性检查挂在这一节末尾，所以上面三张表必须都已出现）
    "ftd",
    "bounce",
    "macro",
    "positions",
    "news",
    "setup",
    "wrapup",        # 今日定位（核心结论）
    "scenario",      # 今日情景 · 对账台账 ← 2026-08-21 Vic：情景和对账是一套东西，合并放最后
]


def _reorder_sections(sections: list, order: list) -> list:
    """按 id 重排小节；未列出的保持原相对次序、排在后面。

    section() 产出的字符串形如 `<section id="xxx" ...>`，这里只读 id 不改内容。
    """
    import re as _re

    def sid(html):
        m = _re.search(r'<section[^>]*id="([^"]+)"', html)
        return m.group(1) if m else ""

    rank = {k: i for i, k in enumerate(order)}
    return sorted(sections, key=lambda h: (rank.get(sid(h), len(order)), sections.index(h)))


def render_premarket(data: dict) -> str:
    date = data.get("date", "")
    generated_at = data.get("generated_at", "")
    title = data.get("title", "盘前简报")
    subtitle = data.get("subtitle", "")
    badges = "".join(
        f'<span class="badge {esc(b.get("kind","blue"))}">{esc(b.get("text",""))}</span>'
        for b in data.get("badges", [])
    )

    # 2026-07-27 Vic大改：「攻守记分板和今日动能打分有点分不清，他们其实指向都应该一样的」。
    # 新顺序=动能打分(先给整体强弱观感) → 攻守记分板(只剩QQQ/SPY两行闸门) → 市宽打分(原记分板里
    # 的广度类条件独立成节)。原"今日动能温度打分"改名"今日动能打分"。
    # 🔴 2026-08-17：目录里摘掉「攻守记分板」——那节已随字段一起退役，
    #    留着就是一条点了没反应的死链（#scoreboard 在页面上已经不存在了）。
    toc_sections = [
        ("signal", "信号灯"), ("risk", "动能打分"),
        ("breadthscore", "市宽打分"), ("ftd", "FTD"),
        ("macro", "宏观"), ("gate", "指数闸门"), ("positions", "持仓"),
        ("news", "消息"), ("movers", "盘前异动"), ("setup", "机会扫描"),
        ("scenario", "情景分析"), ("wrapup", "今日定位"),
    ]

    body_sections = []

    body_sections.append(
        section("signal", "今日信号灯", build_signal_light(data.get("signal_light", {})))
    )

    risk_body = build_risk_bars(data.get("risk_checklist", []))
    note = data.get("risk_checklist_note", "")
    if note:
        risk_body += build_split_callout(note)
    body_sections.append(section("risk", "今日动能打分", risk_body))

    # 2026-07-12 Vic：记分板/温度/联合信号/宏观雷达的分析性文字是"小结"，
    # 用蓝色callout格式渲染，不再是灰色小字（"这些灰色字很重要啊"）
    # 🔴 **攻守记分板 2026-08-17 整块退役**（Vic：「我的攻守记分板删除」）。
    #    实测：21 份报告里归一化后仍有 30 种条件、行数 7~12 从没固定、
    #    最后一份 11 行里 10 行在别处已有。它唯一的功能（升级 N/M 的聚合判断）
    #    由 regime_triggers 承担——那个块本来就是干这个的。
    #    gate_scoreboard_rows 保留：它是 cross_check_alignment 的输入，且是闸门的独立视图。
    # 🔴 gate_scoreboard_rows 2026-08-17 起**不再单独渲染成一节**：
    #    它的 anchor 会和「03 指数闸门」撞车（同 anchor 渲染两次 → 页内跳转失效），
    #    而那几条闸门价位在 03 的 ETF 表里已经逐行列着了。
    #    字段保留：它是 cross_check_alignment 的输入（拿闸门位置和风险清单对表）。

    # 🔴 2026-08-17 两表合一（Vic：「广度明细可以加入市宽打分表格，2表变成一涨」）——
    #    breadth_score_rows 现在就是那张合并表：9 项 Stockbee 明细 + 框架阈值/状态列。
    #    breadth_table 随之退役（模板留空壳）。
    bs_rows = data.get("breadth_score_rows", [])
    if bs_rows:
        bs_body = build_scoreboard_table(bs_rows)
        if data.get("breadth_score_note"):
            bs_body += build_split_callout(data["breadth_score_note"])
        bs_body += build_cross_check(data.get("cross_check", {}))
        if data.get("breadth_table_note"):
            bs_body += build_split_callout(data["breadth_table_note"])
        body_sections.append(section("breadthscore", "市宽打分", bs_body))

    # Follow-Through Day（2026-07-31 Vic带入O'Neil框架：「我们没有做反弹的框架…把反弹加入」）。
    # 放在市宽打分之后——档位讲的是"能不能做"，FTD讲的是"下降趋势结束了没有"，两件事挨着读。
    # **Day 1 由Vic肉眼确认，不自动判定**（他的原话：「第一天我肉眼看，只有在出现第一根绿bar
    # 以后，你才开始观测follow through」）；这里只做计数、Day1低点重置检查、Day 4-7合格判定。
    # 2026-08-07修：原本整节挂在 ftd_table.rows 上，而 FTD 追踪 8/6 起暂停 → 空表 →
    # 连「为什么暂停」那段 note 也一起消失（QA「字段写了却没被渲染」抓到）。
    # 暂停期间那段说明本身就是要读的内容，所以表空但 note 在时照渲染。
    # 2026-08-07 Vic：「ftd和做空你不用显示了，直接放标题，下面放"无"」。
    # 暂停期只留标题 + 「暂停」标记，正文和那段长 note 都不再渲染（它已经写进
    # CONTEXT.md，报告里每天重复一遍是噪音）。恢复：ftd_state.json 的 parked 改 false。
    ftd_state = data.get("ftd") or {}
    if ftd_state.get("parked"):
        body_sections.append(empty_section(
            "ftd", "反弹确认 · Follow-Through Day", "parked",
            "2026-08-06 起暂停追踪（这次 FTD 尝试没有转化成交易动作）。重置线 QQQ 673.30 / VOO 675.21 留档，"
            "恢复需重新肉眼确认 Day 1。详见 CONTEXT.md。"))
    elif (data.get("ftd_table") or {}).get("rows") or data.get("ftd_note"):
        ftd_body = build_table(data["ftd_table"]) if (data.get("ftd_table") or {}).get("rows") else ""
        if data.get("ftd_note"):
            ftd_body += build_split_callout(data["ftd_note"], label="", kind="co-method")
        body_sections.append(section("ftd", "反弹确认 · Follow-Through Day", ftd_body))

    # 反弹品类候选表：2026-08-06 从 FTD 那一节里拆出来独立成节。
    # 原因：它原本挂在 FTD 的 if 里渲染，而 FTD 追踪已暂停 → 整块跟着消失
    # （QA「字段写了却没被渲染」当场抓到）。且 Vic 已把触发器改成口头下达
    # （「触发器我来说触发」），它跟 FTD 在逻辑上也不再是父子关系。
    if (data.get("bounce_table") or {}).get("rows"):
        bounce_body = build_table(data["bounce_table"])
        if data.get("bounce_note"):
            bounce_body += build_split_callout(data["bounce_note"], label="", kind="co-method")
        body_sections.append(section(
            "bounce", "反弹品类候选（ADR≥6% + 深跌 + 已收复9EMA）", bounce_body))
    else:
        body_sections.append(empty_section(
            "bounce", "反弹品类候选（ADR≥6% + 深跌 + 已收复9EMA）", "parked",
            "触发器 2026-08-06 起改由你口头下达（原来挂在 FTD 上，FTD 已暂停）。"
            "筛选条件/仓位上限/失效条件都不变，变的只有「什么时候进」。"))

    # 2026-07-27 Vic："B 放前面去，就是B和A顺序对调"——市宽在前、指数在后。
    macro_parts = []
    atr_rows = data.get("atr_extension_table", [])
    # 2026-07-31 Vic：「市宽打分 和 A·市宽 重复了，删除」——两张表讲的是同4个指标
    # （T2108/5日ratio/10日ratio/涨跌4%+）。保留上面的「市宽打分」（带触发状态、驱动档位判定、
    # 挂着三表一致性检查），A·市宽独有的「前值/变化」两列已并进市宽打分表，信息不丢。
    # A · 离散度（2026-08-06 Vic：「离散度指标单独增加到宏观环境里吧，昨天你的盘前报告，
    # 宏观环境里面都没有A，是从b开始的」）。B 之前空着的那个位置由它补上。
    dsp = data.get("dispersion") or {}
    if dsp.get("ratio") is not None:
        macro_parts.append("<h3>A · 离散度</h3>")
        macro_parts.append(build_dispersion(dsp))
        if data.get("dispersion_note"):
            macro_parts.append(build_split_callout(data["dispersion_note"]))
    # Deemer Breakaway Momentum（2026-08-10 Vic：「deemer 开始读」）——
    # 它是**分母信号**（10日跌家数少到极值），跟 ATR 延伸度不是一类，单独一节。
    if (data.get("bam_table") or {}).get("rows"):
        macro_parts.append("<h3>B · Deemer Breakaway Momentum</h3>")
        # 2026-08-14 Vic：「只显示2天，或者你做成图表」——改成折线图。
        # 逐日表格 10 行数字里只有最后一行有判语，其余 9 行是给眼睛找趋势用的，
        # **那正是图该干的事**。阈值线画出来，「离触发还有多远」一眼可见。
        macro_parts.append(build_bam_chart(data["bam_table"], data.get("bam") or {}))
        if data.get("bam_note"):
            macro_parts.append(build_split_callout(data["bam_note"]))
    # 🔴 2026-08-19 Vic：「voo qqq dia iwm smh rsp qqqe 表格里面好几张，你先都集中到一个地方」——
    #    原「C · 指数」= atr_extension_table（七只的距 50MA ATR 倍数），已并进 03 指数闸门的
    #    index_table（那张表有「距50MA(ATR)」列）。**盘前不再渲染这一块**；
    #    盘后/周报仍在用 build_atr_extension_table，那两处是独立视图，不动。
    # 🔴 D · 其他资产 2026-08-14 Vic：「整个表格删除，我只需要小结」——
    #    表格退役，只渲染 other_assets_note。10Y/VIX/DXY/黄金/白银/WTI/BTC 的数字
    #    本来就只在「信号」列被读，数字本身没人逐行看。
    if data.get("other_assets_note"):
        # 🔴 2026-08-17 Vic：「其他资产里面有两个小结，第一个不是小结，只是陈述」——
        #    这一块是跨资产读数的**陈述**（10Y/金银/TLT/加密各说各的），
        #    真正的小结是紧跟其后的 joint_signal_lines（把它们和股票合起来给结论）。
        #    连着两个「小结：」标题，第二个的分量就被稀释了。label="" 去掉标题行。
        macro_parts.append("<h3>D · 其他资产</h3>")
        macro_parts.append(build_plain_block(data["other_assets_note"]))
    joint_lines = data.get("joint_signal_lines", [])
    if joint_lines:
        # 2026-07-27 Vic：联合信号也走统一的bullet小结格式，不再是<br><br>硬换行
        items = "".join(f'<div class="co-item">{rich(x)}</div>' for x in joint_lines)
        # 🔴 2026-08-20：这里硬编码了「小结：」标题，是 label 默认值改空之后
        #    唯一漏网的一处（Vic：「哈哈你又有两个小结」）。callout 配色已经在说它是小结。
        macro_parts.append(f'<div class="callout"><div class="co-list">{items}</div></div>')
    macro_parts.append("<h3>D · 宏观雷达</h3>")
    macro_parts.append(build_table(data.get("macro_radar_table", {})))
    if data.get("macro_radar_detail"):
        macro_parts.append(build_callout("", data["macro_radar_detail"]))
    macro_parts.append("<h3>E · 板块</h3>")
    for t in data.get("sector_rs_tables", []):
        # 🔴 2026-08-19：「指数基准」组的七只已在 03 指数闸门的 index_table 里，
        #    这里跳过，避免同一组 ticker 在一份报告里画第二遍（Vic：「集中到一个地方」）。
        if "指数" in (t.get("title") or ""):
            continue
        macro_parts.append(f"<h3 style='font-size:15px;color:var(--muted);margin:14px 0 4px'>{esc(t.get('title',''))}</h3>")
        macro_parts.append(build_table(t))
    if data.get("sector_rs_note"):
        macro_parts.append(build_split_callout(data["sector_rs_note"]))
    # 2026-07-27 Vic："防御篮子应该放在主题与国家这个表格后面"——它是regime背景信号，
    # 跟板块RS放一起看才有意义，不该埋在机会扫描里当方法1。
    basket = data.get("defensive_basket", [])
    if basket:
        macro_parts.append("<h3 style='font-size:15px;color:var(--muted);margin:14px 0 4px'>防御观察篮子</h3>")
        macro_parts.append(build_defensive_basket(basket))
        if data.get("leader_vs_defensive_note"):
            macro_parts.append(build_split_callout(data["leader_vs_defensive_note"]))
    scan_table = data.get("unilateral_scan_table", {})
    if scan_table.get("rows"):
        macro_parts.append("<h3>F · 单边板块</h3>")
        macro_parts.append(build_table(scan_table))
        if data.get("unilateral_scan_note"):
            macro_parts.append(build_split_callout(data["unilateral_scan_note"]))
    body_sections.append(section("macro", "01 宏观环境", "".join(macro_parts)))

    # 2026-07-12 Vic：解释性括号文字全部删除（"我晓得的"）；期货表只有数据在时才渲染
    gate_body = ""
    if data.get("futures_table", {}).get("rows"):
        gate_body += "<h3>期货</h3>" + build_table(data["futures_table"])
        if data.get("futures_note"):
            gate_body += build_note_callouts(data["futures_note"])
    # 2026-08-06 Vic 三条：①「（盘前+0.33%）字样直接换一行」②「抬头（atr）那些括号都删除」
    # ③「如果在进攻线，那么进攻线有个绿灯；同理降级线符合有个红灯」
    # 🔴 2026-08-17 Vic：「03 指数闸门这个表格就和上面闸门位置放一起，没必要写两次，
    #    用闸门位置格式」——此前 etf_table（七只 ETF 九列）和 gate_scoreboard_rows
    #    （三只闸门标的卡片式）同页画两遍，VOO/QQQ/IWM 的进攻线在两张表里各写一次。
    #    合成一张，走闸门位置的格式；DIA/SMH/RSP/QQQE 没有闸门线，作参考行（kind="ref"）。
    # 🔴 2026-08-19 Vic 两条：「voo qqq dia iwm smh rsp qqqe 表格里面好几张，你先都集中到一个地方」
    #    「指数闸门能用图示吗？一根横轴看位置」——七只指数原本散在三处
    #    （gate_scoreboard_rows / sector_rs_tables 的「指数基准」组 / atr_extension_table），
    #    现在合成 index_table 一处：ATR 横轴图 + 一张全字段表。另两处已在本函数里停渲。
    # 🔴 2026-08-19 Vic 第二轮：「指数所有表位置放一起，但是格式改回去，让我想想先，
    #    目前新板块没有以前得好」——**位置的合并保留、长相回到旧的三张表**。
    #    所以这一节现在是「三张旧格式的表挨着放」，而不是新的 ATR 横轴图 + 宽表。
    #    `build_index_panel()` **代码留着不删**（他说「让我想想先」），随时可以切回来：
    #    把下面三段换成 `gate_body += build_index_panel(data.get("index_table", []))` 即可。
    gate_body += build_gate_scoreboard(data.get("gate_scoreboard_rows", []))
    for _t in data.get("sector_rs_tables", []):
        if "指数" in (_t.get("title") or "") and _t.get("rows"):
            gate_body += f'<h3>{esc(_t["title"])}</h3>' + build_table(_t)
    _atr = data.get("atr_extension_table", [])
    if _atr:
        # 🔴 2026-08-20 Vic：「有两个小结」——03 这一节原来出两个蓝色小结
        #    （距50MA 表后一个 + 节末 etf_table_note 一个），讲的是同一堆数字。
        #    **一节只留一个小结**，统一由节末的 etf_table_note 收口；
        #    atr_extension_note 在盘前不再单独渲染（盘后/周报那两处不受影响）。
        gate_body += "<h3>距50MA（ATR倍数）</h3>" + build_atr_extension_table(_atr)
    if data.get("etf_table_note"):
        gate_body += build_split_callout(data["etf_table_note"])
    body_sections.append(section("gate", "03 指数闸门", gate_body))

    # 持仓放在宏观之后、机会扫描之前——先做好风控再看机会
    pos_body = "<h3>Moomoo账户</h3>"
    pos_body += build_table(data.get("positions_moomoo_table", {}))
    # 2026-07-15 Vic：LongBridge不再是长持账户（IHI教训——板块长期跑输大盘是有原因的，不给"长持"豁免）
    pos_body += "<h3>LongBridge账户</h3>"
    pos_body += build_table(data.get("positions_longbridge_table", {}))
    # 2026-07-27 Vic："小结应该放在longbridge账户后面"——两个账户都看完再给结论
    if data.get("positions_moomoo_note"):
        pos_body += build_split_callout(data["positions_moomoo_note"])
    # 仓位治理（2026-08-05补）：这一节原本只在盘后渲染，盘前的 position_governance_table
    # 和 _note 写进 JSON 却从来没显示过——QA「字段写了却没被渲染」抓到。
    # 盘前才是真正需要它的时点（下单之前，不是收盘之后）。
    gov_pre = data.get("position_governance_table") or {}
    if gov_pre.get("rows"):
        pos_body += ('<h3 class="gov-head">仓位治理：%d 笔缺持有理由或止损</h3>'
                     % len(gov_pre["rows"]))
        pos_body += build_table(gov_pre)
        if data.get("position_governance_note"):
            pos_body += build_split_callout(data["position_governance_note"],
                                            label="", kind="co-warn")
    # 今晚撤单清单（2026-08-07新增，Vic：「持仓很多时，也许应该只撤那些接近止损的」）。
    # 执行纪律 #8 说「盘前不留挂单」，但十几笔全撤不现实——把「撤哪些」变成按
    # 距止损/ATR 自动算的清单。放在持仓节末尾：看完持仓正好接着决定今晚撤哪几张单。
    sp_tbl = data.get("stop_proximity_table") or {}
    if sp_tbl.get("rows") or data.get("stop_proximity_note"):
        pos_body += "<h3>今晚撤单清单（距止损 &lt;0.7ATR 必撤）</h3>"
        if sp_tbl.get("rows"):
            pos_body += build_table(sp_tbl)
        if data.get("stop_proximity_note"):
            pos_body += build_split_callout(data["stop_proximity_note"],
                                            label="", kind="co-warn")
    # 今日退出执行表（2026-08-11 新增，Vic：「我想盘前止损 glw mrvl soxx aaoi 这几个」
    # →「单独拉一张」）。跟上面的撤单清单**不是一回事，不要合并**：
    #   · 撤单清单 = 全仓自动扫，按距止损/ATR 入选，回答「今晚撤哪几张单」
    #   · 退出执行表 = **Vic 点名的那几笔**，回答「已经决定要出的，今晚怎么出」
    # 放在撤单清单之后：先看撤哪些单，再看已决定要出的怎么执行。
    # 🔴 2026-08-12：Premarket Movers 整节退役（Vic：「我也不看盘前异动选股」）。
    #    渲染层不再输出该节；字段在模板里留空壳，QA 已把它列入 RETIRED_FIELDS。
    ep_tbl = data.get("exit_plan_table") or {}
    if ep_tbl.get("rows") or data.get("exit_plan_note"):
        pos_body += '<h3 class="exit-head">今日退出执行表（你点名的标的）</h3>'
        if ep_tbl.get("rows"):
            pos_body += build_table(ep_tbl)
        if data.get("exit_plan_note"):
            pos_body += build_split_callout(data["exit_plan_note"],
                                            label="", kind="co-warn")
    body_sections.append(section("positions", "持仓", pos_body))

    news_body = ""
    # 专题报告 read-through（2026-08-10 建）。Vic 会直接甩专题报告的链接过来
    # （记忆：「你跑日报时候可以看一下专题报告（注意日期）」），
    # 读完的结论必须落进当天的报告，不能只在对话里说一遍。
    sp = data.get("special_readthrough_table") or {}
    if sp.get("rows"):
        news_body += "<h3>A · 专题报告 read-through</h3>" + build_table(sp)
        if data.get("special_readthrough_note"):
            news_body += build_split_callout(data["special_readthrough_note"])
    today_news = data.get("news_today", [])
    week_news = data.get("news_week", [])
    if today_news:
        # 2026-07-31 Vic：「这里格式又点奇怪」——`news_today` 是二维行（跟盘后的
        # news_tracking 同一种内容），之前被当成字符串列表用 rich() 渲染，
        # 结果整个 Python list literal 打在页面上。改成跟盘后完全同一张表：
        # 时间 / 内容 / 板块 / 市场反应 / 延续（「是」渲染成绿标签）。
        news_body += "<h3>B · 今日盘前重点消息</h3>"
        if today_news and isinstance(today_news[0], (list, tuple)):
            news_body += build_table({
                "headers": ["时间", "内容", "板块", "市场反应", "延续"],
                "rows": today_news, "num_cols": [], "badge_cols": [4],
                "table_class": "fixed-cols",
                "col_widths": ["10%", "40%", "13%", "27%", "10%"]})
        else:   # 旧数据是纯文本列表，保留兼容
            news_body += ('<ul style="padding-left:20px">'
                          + "".join(f'<li style="margin:0 0 7px">{rich(x)}</li>' for x in today_news)
                          + "</ul>")
        if data.get("news_sources"):
            news_body += ('<p class="src-note">出处：'
                          + esc(" · ".join(data["news_sources"])) + "</p>")
    week_cal = data.get("week_calendar", {})
    if week_cal.get("headers"):
        news_body += "<h3>B · 本周重大事件</h3>" + build_week_calendar(week_cal)
    elif week_news:
        news_body += ('<h3>B · 本周重大事件</h3><ul style="padding-left:20px">'
                     + "".join(f'<li style="margin:0 0 6px">{rich(x)}</li>' for x in week_news) + "</ul>")
    # C·行业活动雷达 2026-07-27删除（Vic："我觉得和前面有重复，不如删除吧"）——
    # 内容跟A/B与板块RS表重叠，不再渲染。
    if not news_body:
        news_body = '<p class="placeholder">今日无重点消息。</p>'
    body_sections.append(section("news", "04 宏观消息", news_body))

    # 机会扫描：核心模块，六种找机会的方式合并成一节（2026-07-05：13D/13G和轧空扫描从独立模块并进来，
    # 因为它们本质也是"机会提取"，应该跟其他找机会的方法放一起，不该是散落的独立小节）
    setup_parts = []
    # 🔴 2026-08-20 Vic：EP / momentum burst 这类票盘前报告一直选不出来。
    #    根因不是扫描器不够好，是**这类 setup 的信息不在 T-1 的价格里，在催化剂里**。
    #    所以放在机会扫描最前面——它决定的是「今天要盯谁」，A/B 候选决定「今天做什么形态」。
    cw = data.get("catalyst_watch") or {}
    setup_parts.append("<h3>催化剂在手（事前预案）</h3>")
    setup_parts.append(build_catalyst_watch(cw))
    if data.get("catalyst_watch_note"):
        setup_parts.append(build_split_callout(data["catalyst_watch_note"]))
    # 2026-07-07：避险股+老登合并成一张表、上下排列不再左右分栏（Vic："没地方"）
    # 2026-07-17：ML Leader停用（Vic："leaders既然不再有效，拿掉他们吧，我重新找leader"）——
    # ml_leaders为空时不渲染Market Leader表/方法1标题/联合信号，只留防御篮子表；
    # 新名单确定后ml_leaders非空会自动恢复完整方法1 block。
    # 2026-07-27 Vic：防御篮子挪到「主题与国家」表之后（在01宏观环境里渲染），
    # 方法1恢复成Market Leader本位——Vic自己找到leader后告诉我追踪，没有就留placeholder。
    # 2026-07-31 Vic：「我之前有过很多失效的半导体market leader 请加回去」——名单回归，
    # 但**身份变了**：配合同日建的FTD反弹框架，看的是「谁跌得最惨、现在开始修复」，
    # 不再是旧版的「谁逆势最强」。走 ml_leaders_table（列=修复相关指标：
    # 5日%/距9EMA/距50MA(ATR)/RSI/收盘区间%/距52周高），旧的 ml_leaders 卡片格式保留兼容。
    ml_tbl = data.get("ml_leaders_table") or {}
    ml_leaders = data.get("ml_leaders", [])
    setup_parts.append('<span class="method-tag">方法1 · Market Leader</span>')
    if ml_tbl.get("rows"):
        setup_parts.append(build_table(ml_tbl))
        if data.get("ml_leaders_note"):
            setup_parts.append(build_split_callout(data["ml_leaders_note"], label="", kind="co-method"))
    elif ml_leaders:
        setup_parts.append(build_ml_leaders(ml_leaders))
        # 2026-08-10：note 此前只挂在 ml_leaders_table 分支上，走卡片格式时整段静默丢失
        if data.get("ml_leaders_note"):
            setup_parts.append(build_split_callout(data["ml_leaders_note"], label="", kind="co-method"))
    else:
        # 这里会写整段判断文字，必须用rich()——esc()会把**渲染成字面星号（QA第4条抓到的）
        setup_parts.append('<p class="placeholder">'
                           + rich(data.get("ml_leaders_note")
                                  or "待Vic确定新的Market Leader名单后开始追踪。")
                           + "</p>")

    setup_parts.append('<span class="method-tag">方法2 · 强势板块全量Setup扫描</span>')
    # 🔴 2026-08-20：这行图例一直还写着 A/B/C/D/W/E/Ew —— **Vic 8/20 早就让改成具体的字**
    #    （「我记得我们刚把 setup a b c d 都改成具体的字」），扫描器和表格都改了，
    #    唯独这行说明漏了，于是表里印 "2 wick"、图例里讲 "W 双底"，对不上。

    strong_sector_setups = data.get("strong_sector_setups_table", {})
    setup_parts.append(build_table(strong_sector_setups) if strong_sector_setups.get("rows") else '<p class="placeholder">本次未做强势板块全量技术形态扫描（需要多日K线判断tight consolidation/undercut等结构，LongBridge candlestick接口的参数验证问题仍未解决，暂时只能从板块RS表读超额强弱，不能自动识别具体setup形态），下次盘前继续尝试。</p>')
    # 2026-07-15 Vic：仓位/许可每行都一样没必要占一列，改为表后统一提醒
    if data.get("strong_sector_setups_permission"):
        # 2026-08-20 Vic：「蓝色部分你没改 i ii」——改走 split（罗马数字＋子项分级）
        setup_parts.append(build_split_callout(
            data["strong_sector_setups_permission"], kind="warn"))

    # 🔴 **方法3 · Adanos Top100 扫描 2026-08-17 整块退役**（Vic：「删除这个方法」）。
    #    方法号不重排——方法5/6/7 的编号在 CONTEXT.md 和历史报告里被引用过。
    #    adanos_scan_table / _note 进 RETIRED_FIELDS，模板不再产出。

    # 🔴 方法4 · 盘前异动机会 —— 2026-08-14 Vic：「删除吧 没什么用」，整块退役。
    #    它本来就已经名存实亡：2026-08-12 盘前数据模块整体下线后（Vic：「我也不看盘前异动选股」），
    #    premarket_movers 进了 RETIRED_FIELDS、恒为空，这一节每天渲染的只有一个空标记。
    #    方法号**不重排**——方法5/6/7… 的编号在 CONTEXT.md 和历史报告里被引用过，
    #    重排会让旧报告里的「方法5」指向另一件事。4 号位就留空。
    setup_parts.append('<span class="method-tag">方法5 · X trader setup提取</span>')
    setup_parts.append(build_x_sentiment(data.get("x_sentiment_macro", []), data.get("x_sentiment_stocks", []),
                                         data.get("x_sentiment_macro_summary", "")))
    if data.get("x_sentiment_note"):
        setup_parts.append(build_note_callouts(data["x_sentiment_note"]))
    # X trader台账（2026-08-05补）：原本只在盘后渲染，盘前写了每天丢。
    # 放在X观点池正下方——先看这些账号过去点名的表现，再看他们今天说什么。
    xw = data.get("x_watch_table") or {}
    if xw.get("rows"):
        setup_parts.append("<h3>X trader 台账（历史点名跟踪）</h3>" + build_table(xw))
        if data.get("x_watch_note"):
            setup_parts.append(build_split_callout(data["x_watch_note"]))

    # 方法6 = Vic自己肉眼筛的结果（2026-07-27 Vic："市场好了，我会开始给自己筛的结果"）
    # 2026-07-28 Vic："就把我选的和老师选的都放进盘前报告的setup方法"——加入老师的名单，
    # 用「来源」列区分。同时从纯文字列表升级成表格：这些票都有实测指标（距9EMA/RSI/位置/
    # 机器Setup标签），跟报告其余部分同一种画法，不再是另一种格式。
    setup_parts.append('<span class="method-tag">方法6 · 肉眼筛选（Vic / 老师）</span>')
    vic_tbl = data.get("vic_manual_picks_table", {})
    vic_picks = data.get("vic_manual_picks", [])
    if vic_tbl.get("rows"):
        setup_parts.append(build_table(vic_tbl))
        if data.get("vic_manual_picks_note"):
            setup_parts.append(build_split_callout(data["vic_manual_picks_note"]))
    elif vic_picks:
        setup_parts.append("<ul>" + "".join(f'<li style="margin:0 0 6px">{rich(x)}</li>' for x in vic_picks) + "</ul>")
    else:
        setup_parts.append('<p class="placeholder">待Vic提供——市场转好后由他自己筛选并给出结果。</p>')
    setup_parts.append('<span class="method-tag">方法7 · 机构大额持仓变动（13D/13G）</span>')
    dg_body = build_13dg_table(data.get("thirteen_dg_rows", []))
    if data.get("thirteen_dg_note"):
        dg_body += build_note_callouts(data["thirteen_dg_note"])
    setup_parts.append(dg_body)

    # 方法8 · 轧空扫描：2026-08-07 起**暂停每日扫描**（Vic：「看起来我们没有好的数据，
    # 这样扫出来的轧空部分也没用」）。实测依据：24个交易日里只有1天产出过候选（8/5，
    # 而且是他主动问才做的），iborrowdesk 借券费率源从 7/17 起连续三周不稳定
    # （403/DNS/无响应），而它还活着的那几天结论也是「费率全<2%，无候选」。
    # **保留按需查证**：他点名某只票时用 FINRA 双月短仓 + 每日做空成交量 + 流通股现算
    # （2026-08-07 WOLF 是模板：3分钟拿到五期数据，直接改变了判断）。触发靠他口头说。
    setup_parts.append('<span class="method-tag">方法8 · 轧空候选股扫描</span>')
    squeeze = data.get("squeeze_candidates", [])
    if squeeze:
        squeeze_body = build_squeeze_table(squeeze)
        if data.get("squeeze_note"):
            squeeze_body += build_split_callout(data["squeeze_note"])
        setup_parts.append(squeeze_body)
    else:
        _sq = empty_body(
            "parked",
            "每日扫描 2026-08-07 起暂停（iborrowdesk 借券费率源连续三周不可用；"
            "24 个交易日只产出过 1 次候选）。**改为按需查证**——你点名哪只，用 FINRA 短仓 + 做空成交量现算。")
        # 2026-08-12：parked 时也允许当天补一段 note（此前 note 写了会被静默丢掉）
        if data.get("squeeze_note"):
            _sq += build_split_callout(data["squeeze_note"])
        setup_parts.append(_sq)
    # 事件缺口延续（2026-08-05 建）：独立品类，紧跟轧空之后、A/B/C 之前
    egc = data.get("event_gap_candidates", [])
    if egc:
        eg_body = ('<h3>事件缺口延续（独立品类 · 不进 A/B/C）</h3>'
                   + build_event_gap_table(egc))
        if data.get("event_gap_note"):
            eg_body += build_split_callout(data["event_gap_note"])
        setup_parts.append(eg_body)
    else:
        # 🔴 2026-08-12 修：这里原来贴的是**轧空模块的暂停理由**（FINRA/借券费率），
        #    复制粘贴串了——事件缺口延续**根本没有 parked**，它是「今天没有符合口径的候选」。
        #    两者含义完全相反：一个是「不跑了」，一个是「跑了、没有」。
        #    按「空节三态」规则出 none 标记，并把当天的 note 渲染出来（**表空了更需要说明为什么空**）。
        eg_body = '<h3>事件缺口延续（独立品类 · 不进 A/B/C）</h3>'
        eg_body += empty_body("none", "今日无符合口径的候选（缺口 ≤5% + 具体催化 + 止损能放进 10%）。")
        if data.get("event_gap_note"):
            eg_body += build_split_callout(data["event_gap_note"])
        setup_parts.append(eg_body)

    # 八种方法扫完，汇总成A/B/C候选（最多5个A级 / 7个B级，每天看不了太多）
    # 2026-08-06 Vic：「综合候选·A/B/C分级 这几个字应该是正常标题大小，很重要的板块」
    setup_parts.append('<h3 style="margin-top:22px">综合候选 · A/B/C 分级</h3>')
    # 2026-07-12 Vic："ABC级个股格式不统一"——统一为一张表（watchlist_abc），A/B/C只是"级别"列的值
    abc = data.get("watchlist_abc")
    if abc:
        # 2026-07-27 Vic再提："A/B/C级格式统一吧"——三级共用同一张表、同一组列，
        # 只靠整行底色区分（A=绿 / B=白 / C=灰），不再是"A卡片+B表格+C灰块"三种格式。
        # 2026-07-27 Vic："级别不要放一列，放在上面一行，就不用重复很多次；
        # 来源和板块放在一列叫来源；级别/Ticker记得居中"
        # 🔴 **C 级 2026-08-17 退役**（Vic：「c退役」）。C 级的定义是「当日忽略」——
        #    一个**明说了不做**的清单，对当天的任何决定都不产生输入，
        #    而最后一份里它占了 3/6 行、正文字数约占全表一半。
        #    降级的**理由**仍然要写（那是判断记录），但归到对应模块的 note，
        #    不占候选表的行——**候选表回答的是「今天做什么」。**
        # 🔴 2026-08-19 Vic：「a级setup 如果全绿，就不要填色了」——
        #    A 级本来就整组连在一起、上面还有「A级 · 允许执行」的组标题行，
        #    每行再铺一遍绿底是把**同一个信息说第二遍**；而**颜色只有稀有时才是信号**
        #    （跟 8/18 持仓表退役整行底色是同一条：16 笔里 13 笔上色 = 等于没标）。
        #    组标题已经承担了分级，行底色不再需要。**不要再给这张表加 row_highlights。**
        GRADE_HL = {"A": "", "B": ""}
        GRADE_LABEL = {"A": "A级 · 允许执行", "B": "B级 · 观察为主"}
        rows, hl, groups = [], [], []
        for g in ("A", "B"):
            items = [x for x in abc if (x.get("grade", "") or "").strip()[:1].upper() == g]
            if not items:
                continue
            groups.append(len(rows))
            rows.append([GRADE_LABEL.get(g, g)] + [""] * 6)
            hl.append("")
            for it in items:
                src = " / ".join(x for x in (it.get("sector", ""), it.get("source", ""))
                                 if x and x != "-")
                rows.append([it.get("ticker", ""), src, it.get("setup", ""), it.get("entry", ""),
                             it.get("invalid", ""), it.get("target", ""), it.get("note", "")])
                hl.append(GRADE_HL.get(g, ""))
        setup_parts.append(build_table({
            "headers": ["TICKER", "来源", "Setup", "触发", "失效", "第一目标", "不做/备注"],
            "rows": rows, "num_cols": [], "row_highlights": hl,
            "group_header_rows": groups, "center_cols": [0, 2],
            "table_class": "fixed-cols",
            # 2026-08-06 Vic：「这个表格的列宽给的不合理，setup应该宽，触发列窄对不对」
            # Setup 8%→26%（要放完整形态描述），触发 26%→12%（只是一个价位/一句话）
            "col_widths": ["7%", "14%", "26%", "12%", "11%", "9%", "21%"]}))
        stray_c = [x.get("ticker", "?") for x in abc
                   if (x.get("grade", "") or "").strip()[:1].upper() not in ("A", "B")]
        if stray_c:
            raise ValueError(
                "C 级已于 2026-08-17 退役（Vic：「c退役」），但 watchlist_abc 里还有 %s——"
                "**不要静默丢掉**：把降级理由写进对应模块的 note（方法2 的写 "
                "strong_sector_setups_permission，单边榜的写 unilateral_scan_note），"
                "候选表只留 A/B。" % stray_c)
        setup_parts.append(build_entry_legend())
    else:
        # 2026-07-28 Vic第三次提「A级B级C级setup格式还是不一样的」。前两次（7/12、7/27）都改了
        # watchlist_abc那条路，但旧的三字段分支还留着当兜底——只要assemble写的是
        # watchlist_a/watchlist_b_table/watchlist_c，就会掉回"A卡片+B表格+C灰块"三种格式，
        # 于是每隔几天就漂回去一次。根因不是渲染器不会排，是**还留着一条能漂回去的路**。
        # 所以这里不再兜底，直接报错：三级必须走同一张 watchlist_abc 表，没有第二种画法。
        legacy = [k for k in ("watchlist_a", "watchlist_b_table", "watchlist_c") if data.get(k)]
        if legacy:
            raise ValueError(
                f"A/B/C候选请写进 watchlist_abc（每条带 grade: A/B/C），不要再用 {legacy}——"
                "旧字段会渲染成三种不同格式，Vic已要求统一三次。"
                "字段：ticker/sector/source/setup/entry/invalid/target/note/grade"
            )
        setup_parts.append('<p class="placeholder">今日无A/B/C级候选。</p>')
    if data.get("setup_conclusion"):
        setup_parts.append(build_split_callout(data["setup_conclusion"]))
    body_sections.append(section("setup", "机会扫描 / Setup（核心）", "".join(setup_parts)))

    # 🔗 2026-08-21 Vic：「今日情景分析 和盘后对账其实是一套东西，合并放在最后吧」——
    #    情景说的是「如果 A 就做 X」，对账台账说的是「A 会不会发生、我给多少概率」，
    #    **是同一件事的两半**。原来一个在中段、一个在末尾，读的时候要自己接回去。
    #    现在：今日定位（核心结论）在前，情景 ＋ 对账台账合成最后一节。
    #    顺序变更已同步进 qa_report.REPORT_SPEC["premarket"]["sections"]（QA 会比对两边）。

    # 今日定位（只留核心结论）。2026-07-27 Vic三处精简：
    # ①删「油门升级/降级讯号」——降级线触发了他也不会真降级（7/27大跌当天一条都没触发，证明这组线没用）
    # ②KEY TAKEAWAYS只保留一个标题，不再"kicker+h3"重复两次
    # ③删黄色「今日定位」指令块——内容跟A/B/C候选表重复，反向信号已并进那张表的「不做/备注」列
    wrapup_body = build_key_takeaways(data.get("key_takeaways", []))
    body_sections.append(section("wrapup", "今日定位", wrapup_body))

    # 最后一节：情景 ＋ 对账台账（2026-08-21 合并）
    sc_body = build_playbook_scenarios(data.get("playbook_scenarios", []))
    sc_body += '<h3 style="margin-top:24px">盘后对账清单</h3>'
    sc_body += build_recon_ledger(data.get("recon_ledger", []))
    # 事前概率的口径说明（2026-08-08 建）。盘后一直有渲染，盘前漏了——
    # 而盘前才是概率被**写下**的地方，说明放在这里比放盘后更重要。
    if data.get("recon_prob_note"):
        sc_body += f'<p class="brier-line">{rich(data["recon_prob_note"])}</p>'
    body_sections.append(section("scenario", "今日情景 · 对账台账", sc_body))

    # 2026-07-05：13F→13D/13G、轧空、国会交易、Polymarket全部已解决（13D/13G和轧空并进了机会扫描，
    # 国会交易走X观点池），"待接入"暂时是空的，先不渲染这个section；等真出现新的没数据源的模块再加回来

    # 2026-08-10：四处渲染器都直接 esc(footer)，而 assemble 侧一直写的是 list——
    # 结果页脚被打印成 Python 的 list repr（['LongPort OpenAPI', ...]）。
    # 四个报告类型全中，没人报过：页脚没人看，正是「无反馈回路」那类静默缺陷。
    footer = data.get("footer_sources", "")
    if isinstance(footer, (list, tuple)):
        footer = " · ".join(str(x) for x in footer)

    # 🔴 2026-08-19 Vic：「三个角度分歧：闸门位置=中性、市宽打分=偏空、动能打分=偏空
    #    既然这样 闸门位置提到市宽上面」
    #    根因不是审美：**三表一致性检查（build_cross_check）挂在「市宽打分」那一节的末尾**，
    #    而它点名的三个角度里，「闸门位置」原本排在第 7 节 —— 读到那句「三个角度分歧」时，
    #    读者还没看过其中一个角度。把闸门提到市宽之前，三张表就都在结论之前出现了。
    #    顺序在这里收口（按 id 重排），不要回到各 append 点各改一次。
    body_sections = _reorder_sections(body_sections, PREMARKET_SECTION_ORDER)

    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(date)} 美股盘前监控｜{esc(title)}</title>
<style>
{CSS_PATH.read_text(encoding="utf-8")}
</style>
</head>
<body data-report-type="premarket"><main class="wrap">
<header>
  <div class="eyebrow">美股盘前监控 · {esc(date)} · {esc(generated_at)}</div>
  <h1>{esc(title)}</h1>
  {f'<p class="muted note">{rich(subtitle)}</p>' if subtitle else ''}
  {f'<div class="badges">{badges}</div>' if badges else ''}
</header>
{build_toc(toc_sections)}
{''.join(body_sections)}
<footer class="source"><p>{esc(footer)}</p></footer>
</main></body>
</html>
"""


def render_postmarket(data: dict) -> str:
    date = data.get("date", "")
    generated_at = data.get("generated_at", "")
    title = data.get("title", "盘后对账")
    subtitle = data.get("subtitle", "")
    badges = "".join(
        f'<span class="badge {esc(b.get("kind","blue"))}">{esc(b.get("text",""))}</span>'
        for b in data.get("badges", [])
    )

    # 2026-07-15 Vic重排：theme/setupa/xwatch三节挨在一起（"都看选股"），放在01收盘总结之后、
    # 03财报之前；命中率之后直接接教训，Setup A对账不再单独占顶部位置
    toc_sections = [
        ("recon", "盘后对账"), ("hitrate", "命中率"), ("lessons", "迭代"),
        ("newswatch", "隔夜新闻"), ("close", "收盘总结"),
        ("breadth", "市场广度"), ("setupa", "Setup A对账"), ("xwatch", "X台账"),
        ("earnings", "财报复盘"), ("positions", "持仓跟踪"), ("ml", "Market Leader"),
        ("outlook", "明日前瞻"),
    ]

    body_sections = []

    # 2026-07-28 Vic：「盘后对账这个标题放在spy qqq smh breath标签下面吧」——四张收盘卡是
    # 全局读数（今天市场怎么走），不属于「对账」这件事；标题压在它们下面，对账从命中条开始。
    hit = data.get("hit_count", 0)
    partial = data.get("partial_count", 0)
    miss = data.get("miss_count", 0)
    recon_body = build_hitbar(hit, partial, miss)
    recon_body += build_recon_table(data.get("recon_rows", []))
    # 🔴 2026-08-17 Vic：「brier score 就放周报吧」。
    #    **8/17 那次没删干净**：我只写了注释说已删，渲染代码原样留着，
    #    还把 Brier 数字和判语写进了 recon_prob_note——绕一圈放回去了。
    #    Vic 8/18 引原文问「不是说这句话删了嘛？」。**注释宣布的改动不算改动。**
    #    现在 recon_prob_note 的语义收窄成「概率口径」：只说概率怎么定、为什么不许盘后改，
    #    **不出现任何 Brier 数字或判语**（QA `_no_daily_brier` 会红）。
    #    Brier 仍然逐日算、逐日进 JSON（每行的 prob + result 都在），
    #    **判语只在周报出**——那里一周 ~20 条，n 才够。
    if data.get("recon_prob_note"):
        recon_body += f'<p class="brier-line">{rich(data["recon_prob_note"])}</p>'
    if data.get("recon_note"):
        recon_body += build_split_callout(data["recon_note"])
    # 🔴 2026-08-20 Vic：「这个改成和盘前报告一样的闸门格式吧？有颜色容易看」——
    #    收盘四张卡（VOO/QQQ/SMH/广度）换成**盘前那张闸门表**：
    #    同一个 build_gate_scoreboard、同一组 GATE_TICKERS、状态列同一套配色。
    #    **盘前盘后同一件事就该长同一个样**（跟 8/18 持仓表统一是同一条）。
    #    广度不在闸门表里（它没有进攻线/防守线）——它本来就有独立的「市宽」一节承载，
    #    塞进闸门表就等于又造一行「四列全是横杠」的参考行，那正是 8/20 刚删掉的东西。
    _gate = data.get("gate_scoreboard_rows") or []
    _top = (section("closegate", "收盘 · 闸门位置", build_gate_scoreboard(_gate)
                    + (build_split_callout(data["close_gate_note"])
                       if data.get("close_gate_note") else ""))
            if _gate else build_summary_cards(data.get("close_summary_cards", [])))
    body_sections.append(_top + section("recon", "盘后对账", recon_body))

    hr = data.get("hit_rate_stats", {})
    hr_rows = []
    for label, key in [("今日", "today"), ("本周", "week"), ("30日滚动", "rolling30")]:
        s = hr.get(key)
        if s:
            hr_rows.append([label, str(s.get("hit", 0)), str(s.get("partial", 0)), str(s.get("miss", 0)), s.get("rate", "")])
    hr_table = {"headers": ["周期", "命中", "部分", "失误", "命中率"], "rows": hr_rows,
                "num_cols": [], "center_cols": [1, 2, 3, 4], "table_class": "fixed-cols",
                "col_widths": ["24%", "19%", "19%", "19%", "19%"]}
    body_sections.append(section("hitrate", "命中率统计", build_table(hr_table)))

    iters = data.get("iterations") or _iterations_from_legacy(
        data.get("lessons", {}), data.get("corrections", []))
    body_sections.append(section("lessons", "本日迭代", build_iterations(iters)))

    # 2026-07-28 Vic：「TradeBook盘后总结输出删除这个部分，你每次自己可以直接输入到tradebook」

    # 隔夜新闻追踪（2026-07-08建，2026-07-28 Vic five处改版：
    # ①改名「隔夜新闻追踪」，只追 SGT 20:00 → 次日 SGT 09:00 这一段的大事
    # ②删「来源」列——出处放表格后面的引用注释，不占正文宽度
    # ③「涉及板块」只写板块，不写个股列表
    # ④「市场反应」只给数字（SNDK -11%），不写解释性文字
    # ⑤「明日是否延续关注」改叫「延续」，值为「是」时渲染成绿标签
    news_rows = data.get("news_tracking", [])
    if news_rows:
        nt_body = build_table({
            "headers": ["时间", "内容", "板块", "市场反应", "延续"],
            "rows": news_rows, "num_cols": [], "badge_cols": [4],
            "table_class": "fixed-cols",
            "col_widths": ["10%", "40%", "13%", "27%", "10%"]})
        if data.get("news_sources"):
            nt_body += ('<p class="src-note">出处：'
                        + esc(" · ".join(data["news_sources"])) + "</p>")
        if data.get("news_tracking_note"):
            nt_body += build_split_callout(data["news_tracking_note"])
        body_sections.append(section("newswatch", "隔夜新闻追踪", nt_body))

    # 01收盘总结：index_table已是"指数+盘中区间位置"合体表（2026-07-11定的规则，2026-07-15修正
    # 当天违反的一次实现——之前拆成了index_table+intraday_range_table两张表，现在合回一张）
    # 2026-07-28 Vic：「ETF板块表格应该直接承接收盘总结第一个表格，而且两个表格格式一样的」
    # ——两张表用同一组headers/col_widths，中间不插callout，看起来是一张表的两段；
    # 两段的小结都挪到下面，不打断表与表的衔接。
    # 指数表 + 板块表用同一组headers/col_widths，中间不插任何东西——Vic要它们看起来是
    # 一张表的两段。ATR延伸表和两段小结都排在这两张表之后。
    close_body = build_table(data.get("index_table", {}))
    close_body += build_table(data.get("sector_table", {}))
    # 🔴 2026-08-21 Vic：「这两个小结是应该放一起，第二次错哦」——
    #    指数表小结和板块表小结**渲染成一块 callout**，不是上下两块。
    #    它们本来就都排在两张表之后（CONTEXT「中间不插任何东西」），
    #    但拆成两个蓝框之后，读的人要在两个框之间自己接一次；
    #    而这两段说的是同一件事的两个层（指数怎么走 / 板块怎么排）。
    #    2026-07-28 的板块四件套规则不变，只是它现在挂在合并块的后半段。
    _notes = [data.get("index_table_note"), data.get("sector_table_note")]
    _notes = [x for x in _notes if x]
    if _notes:
        close_body += build_split_callout(chr(10).join(_notes))
    # 2026-08-06 Vic：「软件细分单独开一个表格，里面有 igv cibr arkk xsw」——
    # 盘前已经分出来了，盘后一直没接上，等于同一份分组只做了一半。
    if (data.get("sector_soft_table") or {}).get("rows"):
        close_body += "<h3>软件细分</h3>" + build_table(data["sector_soft_table"])
        if data.get("sector_soft_note"):
            close_body += build_split_callout(data["sector_soft_note"])
    # 2026-07-28：盘前的「B·指数」50MA ATR延伸表同样接进盘后
    atr_rows = data.get("atr_extension_table", [])
    if atr_rows:
        close_body += "<h3>50MA距离</h3>" + build_atr_extension_table(atr_rows)
        if data.get("atr_extension_note"):
            close_body += build_split_callout(data["atr_extension_note"])
    body_sections.append(section("close", "01 收盘总结", close_body))

    # 02 市场广度。2026-07-21 建时数据来自 Vic 提供的 S&P500 全量市宽 tab；
    # 🔴 **2026-08-14 起数据源改为单一的 Stockbee 公开表**（Vic：「以后只用 stockbee，其他删除」），
    #    由 assemble 侧的 breadth_rows() 直接从 cache["stockbee"] 生成。
    #    sp500_breadth / maket_breath 两个源已在 fetch_market_data.py 退役成空壳。
    bt = data.get("breadth_live_table", {})
    if bt.get("rows"):
        br_body = build_table(bt)
        if data.get("breadth_score_note"):
            br_body += build_split_callout(data["breadth_score_note"])
        # 2026-08-05补：盘后的 ftd / ftd_table / ftd_note 之前只有表没有 note（note 只在盘前渲染）
        # 2026-08-07修①：这段原本把 body_sections.append 也缩进在 `ftd_table.rows` 的 if 里，
        # FTD 追踪 8/6 暂停后 ftd_table 变成空表 → 整个「02 市场广度」节连同 note 一起消失
        # （QA「字段写了却没被渲染」+「缺少必备节 breadth」当场抓到）。
        # 2026-08-07修②：暂停期只留一行「暂停」标记，不再每天重复那段长说明（已进 CONTEXT.md）。
        if (data.get("ftd") or {}).get("parked"):
            br_body += "<h3>反弹确认 · Follow-Through Day</h3>"
            br_body += empty_body("parked", "2026-08-06 起暂停追踪。重置线 QQQ 673.30 / VOO 675.21 留档。")
        elif data.get("ftd_note"):
            br_body += build_split_callout(data["ftd_note"])
        # 2026-08-11 Vic：「Weinstein 728 票全扫 用不着 stage 了，这个删除」——
        # breadth_stage_table / breadth_stage_note 主动退役，渲染块删除（同 breadth_history_table
        # 2026-07-28 的处理方式）。两个字段在 assemble_template_postmarket.py 里留空壳带退役日期，
        # qa_report.RETIRED_POSTMARKET_FIELDS 也登记了——**是主动退役，不是漂移丢失**。
        # 2026-07-28 Vic：「近期逐日走势（newest first）整个表格删除」
        body_sections.append(section("breadth", "02 市场广度", br_body))

    # Setup A专项对账 + X trader台账（2026-07-15 Vic："和我选的ab setup放近些…都看选股"——
    # 两节都是"选了什么、走成什么样"的复盘，放一起方便一次看完；02主线复盘已于2026-07-16退役）
    # 2026-08-07：窗口内无跟踪条目时（如当天A级为空）表是空的，但 note 要说明"为什么空"——
    # 空表不渲染表格，节本身照渲染，否则整节静默消失。
    setup_a_table = data.get("setup_a_track_table", {})
    sa_body = build_table(setup_a_table) if setup_a_table.get("rows") else ""
    if not sa_body:
        # 窗口内无跟踪条目（当天A级为空 / 全部满窗归档）——「无」不是「没跑」
        sa_body = empty_body("none", "窗口内无跟踪中的条目（当天 A 级为空，或已有条目全部满 5 日窗口归档）。")
    if data.get("setup_a_track_note"):
        sa_body += build_split_callout(data["setup_a_track_note"])
    # 🔴 2026-08-20 改名：字母退役后「Setup A 专项对账」这个名字既不准也误导——
    #    它现在跟的是**当天放行的全部 A 级候选**，不分形态。
    body_sections.append(section("setupa", "A 级候选跟踪（连续 5 个交易日）", sa_body))

    x_watch_table = data.get("x_watch_table", {})
    if x_watch_table.get("rows"):
        xw_body = build_table(x_watch_table)
        if data.get("x_watch_note"):
            xw_body += build_split_callout(data["x_watch_note"])
        body_sections.append(section("xwatch", "X trader台账跟踪", xw_body))

    # 🔴 2026-08-12：note 不能挂在「表有行」上——2026-08-11 盘后 earnings_note 写了整段
    #    却因为表是空的被整块丢掉（QA「字段写了却没被渲染」抓到）。这是「空节三态」那条规则的
    #    同一个失败模式：**表空了更需要说明为什么空**。
    earnings_table = data.get("earnings_table", {})
    if earnings_table.get("rows") or data.get("earnings_note"):
        _eb = build_table(earnings_table) if earnings_table.get("rows") else ""
        if data.get("earnings_note"):
            # 🔴 2026-08-20 Vic：「这个不是小结，直接用白色表格吧」——
            #    财报那段是**陈述**（谁报了、超没超、盘面怎么反应），判断只是其中一句。
            #    蓝底 callout 在这份报告里有固定含义 ＝「这是判断」，用错了就等于
            #    告诉眼睛「这块和真正的小结一样重」。走白底陈述块（同 D·其他资产）。
            _eb += build_plain_block(data["earnings_note"])
        body_sections.append(section("earnings", "03 财报复盘", _eb))
    else:
        body_sections.append(placeholder_section("earnings", "03 财报复盘", "今日无重大财报。"))

    pos_body = "<h3>Moomoo账户</h3>"
    pos_body += build_table(data.get("positions_moomoo_table", {}))
    # 2026-07-15 Vic：LongBridge不再是长持账户（IHI教训，见CONTEXT.md身份与背景）
    pos_body += "<h3>LongBridge账户</h3>"
    pos_body += build_table(data.get("positions_longbridge_table", {}))
    if data.get("positions_moomoo_note"):
        pos_body += build_split_callout(data["positions_moomoo_note"])
    # 持仓治理（2026-08-01 Vic批准启用为硬性规则）：thesis为空或止损为空的仓位
    # **标红单列一节**，不再只在持仓表备注里提一句——「每笔仓位都有持有理由」
    # 已连续两周未做到，按CONTEXT「同一缺口连续两周→升级为硬性规则」处理。
    # 🔴 2026-08-19：note 不再挂在「表有行」的条件下（这是同一个坑的**第四次**，
    #    前三次记在 CONTEXT「note 不能挂在表有行的条件下」）。**治理表为空恰恰是要说明的状态**——
    #    「今天没有缺持有理由的仓位」和「这一节被整块吞掉」在页面上长得一模一样。
    gov = data.get("position_governance_table") or {}
    if gov.get("rows") or data.get("position_governance_note"):
        pos_body += ('<h3 class="gov-head">仓位治理：%d 笔缺持有理由或止损</h3>'
                     % len(gov.get("rows") or [])) if gov.get("rows") else                     '<h3 class="gov-head">仓位治理</h3>'
        if gov.get("rows"):
            pos_body += build_table(gov)
        if data.get("position_governance_note"):
            pos_body += build_split_callout(data["position_governance_note"],
                                            label="", kind="co-warn")
    # 教材 p14 持仓管理执行表（2026-08-14 接入）。为什么它排在持仓表之后、代理RS之前：
    # 51 笔跟单实测显示曾浮盈 ≥10% 的 18 笔里 13 笔最终 ≤0% 收场（平均放走 22.4pt），
    # 而选股评分对峰值没有预测力——**亏钱的地方是持有和退出，不是选股**。
    # 🔴 数据日不对时 helper 返回 nodata 而不是错数，这里要把它渲染出来，不能整节消失。
    pmt = data.get("position_manage_table") or {}
    if pmt.get("rows") or pmt.get("nodata") or data.get("position_manage_note"):
        pos_body += '<h3>持仓管理执行表</h3>'
        if pmt.get("rows"):
            pos_body += build_table(pmt)
        else:
            pos_body += empty_body("nodata", pmt.get("nodata", ""))
        if data.get("position_manage_note"):
            pos_body += build_split_callout(data["position_manage_note"])
    # 代理/杠杆型仓位 vs 母体的相对强弱（2026-08-06 建，用于论点退出触发）。
    # 建的当天就在 helpers 里算了，但渲染层一直没接——WGMI 的退出信号只出现在 iterations
    # 的文字里，那张表从来没渲染过。同一批静默丢失里最隐蔽的一个。
    prs = data.get("proxy_rs_table") or {}
    if prs.get("rows") or data.get("proxy_rs_note"):
        pos_body += "<h3>代理相对强弱（论点退出）</h3>"
        if prs.get("rows"):
            pos_body += build_table(prs)
        if data.get("proxy_rs_note"):
            pos_body += build_split_callout(data["proxy_rs_note"])
    body_sections.append(section("positions", "04 持仓跟踪", pos_body))

    # 2026-07-17：ML Leader停用（Vic重新找leader中），名单为空时不渲染整节，
    # 不留空壳（同「已解决的parked section」处理原则）
    ml_rows_pm = data.get("ml_leaders_postmarket", [])
    # 2026-08-05修：原本整节挂在 ml_rows_pm 非空上，而 ML Leader 自 7/17 起停用（空list），
    # 导致 ml_tier_change / ml_tomorrow_watch 这两段方法论**连着被跳过了半个多月**——
    # 其中 ml_tomorrow_watch 写的是明日核心矛盾，跟名单空不空无关。改成：名单空也渲染这两段。
    if ml_rows_pm or data.get("ml_tier_change") or data.get("ml_tomorrow_watch"):
        ml_body = build_ml_leaders_postmarket(ml_rows_pm) if ml_rows_pm else ""
        # 2026-07-28 Vic：「下面两段方法论挺重要，用类似小结格式吧」→ 再修：
        # 「两个小结呢，而且我觉得这属于方法论，不如你用绿色或者黄色，而且应该放一起」
        # ——两段合成一块、标签改「方法论」、配色改黄（与核心纪律/今日定位同族：
        # 黄=「怎么做/规则」，蓝=「发生了什么」，不再跟普通小结撞色）
        meth = "；".join(x for x in (data.get("ml_tier_change"),
                                     data.get("ml_tomorrow_watch")) if x)
        if meth:
            ml_body += build_split_callout(meth, label="", kind="co-method")
        body_sections.append(section("ml", "Market Leader", ml_body))

    # 2026-07-28 Vic：「明日前瞻太长了，写简洁点，然后给个白底，容易阅读」
    outlook_items = data.get("next_day_outlook", [])
    outlook_body = ('<ol class="outlook-list">' + "".join(
        f"<li>{rich(x)}</li>" for x in outlook_items) + "</ol>"
    ) if outlook_items else '<p class="placeholder">待补充。</p>'
    body_sections.append(section("outlook", "05 明日前瞻", outlook_body))

    # 2026-08-10：四处渲染器都直接 esc(footer)，而 assemble 侧一直写的是 list——
    # 结果页脚被打印成 Python 的 list repr（['LongPort OpenAPI', ...]）。
    # 四个报告类型全中，没人报过：页脚没人看，正是「无反馈回路」那类静默缺陷。
    footer = data.get("footer_sources", "")
    if isinstance(footer, (list, tuple)):
        footer = " · ".join(str(x) for x in footer)

    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(date)} 美股盘后对账｜{esc(title)}</title>
<style>
{CSS_PATH.read_text(encoding="utf-8")}
</style>
</head>
<body data-report-type="postmarket"><main class="wrap">
<header>
  <div class="eyebrow">美股盘后对账 · {esc(date)} · {esc(generated_at)}</div>
  <h1>{esc(title)}</h1>
  {f'<p class="muted note">{rich(subtitle)}</p>' if subtitle else ''}
  {f'<div class="badges">{badges}</div>' if badges else ''}
</header>
{build_toc(toc_sections)}
{''.join(body_sections)}
<footer class="source"><p>{esc(footer)}</p></footer>
</main></body>
</html>
"""


def render_weekly(data: dict) -> str:
    """周报渲染器（2026-08-01建，Vic：「周末为什么不用渲染和json? 格式差不多的，不要手写啊」）。

    此前 W28-W30 三份周报都是手写HTML——**周报因此是唯一不过QA的报告**，
    格式必然漂，而且每周重复劳动。这里改成跟盘前/盘后同一条流水线：
    JSON → render_report.py → 自动QA。所有区块复用已有builder，不新造轮子。

    章节顺序按 CONTEXT.md「周报」章节 + 2026-07-18 对标老师周报新增的固定格式。
    """
    week = data.get("week", "")
    title = data.get("title", "周总结")
    subtitle = data.get("subtitle", "")
    generated_at = data.get("generated_at", "")
    badges = "".join(
        f'<span class="badge {esc(b.get("kind","blue"))}">{esc(b.get("text",""))}</span>'
        for b in data.get("badges", []))

    toc, body = [], []

    def sec(anchor, title_, inner):
        toc.append((anchor, title_))
        body.append(section(anchor, title_, inner))

    # ① 五个核心周结论（开头，带数字的bullet）+ 本周定位
    if data.get("core_conclusions"):
        b = build_key_takeaways(data["core_conclusions"])
        if data.get("week_stance"):
            b += build_split_callout(data["week_stance"], label="本周定位", kind="co-method")
        sec("core", "本周五个核心结论", b)

    # ② 升级/降级双框（复用盘前记分板样式）
    if data.get("regime_rows"):
        b = build_scoreboard_table(data["regime_rows"])
        if data.get("regime_note"):
            b += build_split_callout(data["regime_note"])
        sec("regime", "升级 / 降级双框", b)

    # ③ 本周行情：指数卡片 + 五天剧本 + 指数ETF复盘 + 50MA ATR周延伸
    parts = build_summary_cards(data.get("week_cards", []))
    if (data.get("five_day_table") or {}).get("rows"):
        parts += "<h3>五天剧本</h3>" + build_table(data["five_day_table"])
    if (data.get("index_review_table") or {}).get("rows"):
        parts += "<h3>指数ETF复盘</h3>" + build_table(data["index_review_table"])
        if data.get("index_review_note"):
            parts += build_split_callout(data["index_review_note"])
    if data.get("atr_extension_table"):
        parts += "<h3>50MA距离（周）</h3>" + build_atr_extension_table(data["atr_extension_table"])
        if data.get("atr_extension_note"):
            parts += build_split_callout(data["atr_extension_note"])
    if parts:
        sec("market", "一、本周行情", parts)

    # ④ Big Winners / Losers（个股层面是否推翻ETF层面判断）
    wl = ""
    for key, h3 in (("winners_table", "Big Winners"), ("losers_table", "Big Losers")):
        if (data.get(key) or {}).get("rows"):
            wl += f"<h3>{h3}</h3>" + build_table(data[key])
    if wl:
        if data.get("winners_losers_note"):
            wl += build_split_callout(data["winners_losers_note"])
        sec("winners", "二、个股层面：Winners / Losers", wl)

    # ⑤ 上周对账（监控清单逐行验证，四分法）
    if (data.get("last_week_recon_table") or {}).get("rows"):
        b = build_table(data["last_week_recon_table"])
        if data.get("behavior_goals_table", {}).get("rows"):
            b += "<h3>上周行为目标核对</h3>" + build_table(data["behavior_goals_table"])
        if data.get("last_week_recon_note"):
            b += build_split_callout(data["last_week_recon_note"])
        sec("lastweek", "三、上周对账（监控清单逐行验证）", b)

    # ⑥ 交易复盘
    tr = ""
    # 🔴 2026-08-17 加 exec_quality_table（Vic：「你的周报里面没有分析我的一周交易」）。
    #    CONTEXT 周报②要求四样，此前只做了三样——缺的正是唯一算「分析」的那样：
    #    **重复模式 vs 做对的事**。这张表量的是买卖点在当日区间的位置 + 是否触及止损，
    #    三个数都不依赖事后叙事，避免复盘变成讲故事。
    for key, h3 in (("closed_trades_table", "本周平仓明细"),
                    ("trade_stats_table", "分口径统计（自主 / 跟单 / 日内）"),
                    ("exec_quality_table", "执行质量：买卖点在当日区间的位置"),
                    ("open_positions_table", "持仓中")):
        if (data.get(key) or {}).get("rows"):
            tr += f"<h3>{h3}</h3>" + build_table(data[key])
    if tr:
        if data.get("trade_review_note"):
            tr += build_split_callout(data["trade_review_note"])
        sec("trades", "四、交易复盘", tr)

    # ⑦ 系统对账
    if (data.get("system_recon_table") or {}).get("rows"):
        b = build_table(data["system_recon_table"])
        if data.get("system_recon_note"):
            b += build_split_callout(data["system_recon_note"])
        sec("system", "五、系统对账", b)

    # ⑧ 大盘修正风险清单（8项 + N/8评分）
    if data.get("correction_checklist"):
        b = build_risk_bars(data["correction_checklist"])
        if data.get("correction_note"):
            b += build_split_callout(data["correction_note"])
        sec("correction", "六、大盘修正风险清单", b)

    # ⑨ 外汇商品美债 + 宏观Fed路径
    macro = ""
    for key, h3 in (("cross_asset_table", "外汇、商品与美债"),
                    ("macro_table", "宏观与Fed路径")):
        if (data.get(key) or {}).get("rows"):
            macro += f"<h3>{h3}</h3>" + build_table(data[key])
    if macro:
        if data.get("macro_note"):
            macro += build_split_callout(data["macro_note"])
        sec("macro", "七、跨资产与宏观", macro)

    # ⑩ Cross-validation：确认 / 分歧 / 主结论
    cv = ""
    for key, label, kind in (("cv_aligned", "互相确认", "co-good"),
                             ("cv_split", "互相分歧", "co-warn"),
                             ("cv_conclusion", "主结论", "co-method")):
        if data.get(key):
            cv += build_split_callout(data[key], label=label, kind=kind)
    if cv:
        sec("crossval", "八、Cross-validation", cv)

    # ⑪ 本周框架进化
    if data.get("framework_changes"):
        sec("framework", "九、本周框架进化",
            build_iterations(data["framework_changes"]))

    # ⑫ 下周计划：日历 + 监控清单 + 行为目标 + 核心立场
    nx = ""
    if (data.get("next_week_calendar") or {}).get("headers"):
        nx += "<h3>下周日历</h3>" + build_week_calendar(data["next_week_calendar"])
    if (data.get("watch_checklist_table") or {}).get("rows"):
        nx += "<h3>下周监控清单</h3>" + build_table(data["watch_checklist_table"])
    if data.get("next_week_plan"):
        nx += "<h3>下周交易计划（每条自带反向信号）</h3>"
        nx += '<ol class="outlook-list">' + "".join(
            f"<li>{rich(x)}</li>" for x in data["next_week_plan"]) + "</ol>"
    if data.get("behavior_targets"):
        nx += build_split_callout("；".join(data["behavior_targets"]),
                                  label="下周行为目标", kind="co-method")
    if data.get("stance_one_liner"):
        nx += build_split_callout(data["stance_one_liner"], label="核心立场", kind="co-method")
    if nx:
        sec("nextweek", "十、下周计划", nx)

    # 2026-08-10：四处渲染器都直接 esc(footer)，而 assemble 侧一直写的是 list——
    # 结果页脚被打印成 Python 的 list repr（['LongPort OpenAPI', ...]）。
    # 四个报告类型全中，没人报过：页脚没人看，正是「无反馈回路」那类静默缺陷。
    footer = data.get("footer_sources", "")
    if isinstance(footer, (list, tuple)):
        footer = " · ".join(str(x) for x in footer)
    if isinstance(footer, list):
        footer = " · ".join(footer)
    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(week)} 周总结｜{esc(title)}</title>
<style>
{CSS_PATH.read_text(encoding="utf-8")}
</style>
</head>
<body data-report-type="weekly"><main class="wrap">
<header>
  <div class="eyebrow">美股周总结 · {esc(week)} · {esc(generated_at)}</div>
  <h1>{esc(title)}</h1>
  {f'<p class="muted note">{rich(subtitle)}</p>' if subtitle else ''}
  {f'<div class="badges">{badges}</div>' if badges else ''}
</header>
{build_toc(toc)}
{''.join(body)}
<footer class="source"><p>{esc(footer)}</p></footer>
</main></body>
</html>
"""


def render_monthly(data: dict) -> str:
    """月报渲染器（2026-08-01建，Vic：「其实本周应该跑每月总结的。。这个也要渲染」）。

    跟周报共用同一套builder，只是章节按月度尺度重排：
    月度不看「五天剧本」看「四周脉络」，不看「上周对账」看「月度框架进化总账」，
    交易统计按口径（自主/跟单/日内）做全月汇总而不是单周。
    """
    month = data.get("month", "")
    title = data.get("title", "月总结")
    subtitle = data.get("subtitle", "")
    generated_at = data.get("generated_at", "")
    badges = "".join(
        f'<span class="badge {esc(b.get("kind","blue"))}">{esc(b.get("text",""))}</span>'
        for b in data.get("badges", []))
    toc, body = [], []

    def sec(anchor, title_, inner):
        toc.append((anchor, title_))
        body.append(section(anchor, title_, inner))

    if data.get("core_conclusions"):
        b = build_key_takeaways(data["core_conclusions"])
        if data.get("month_stance"):
            b += build_split_callout(data["month_stance"], label="本月定位", kind="co-method")
        sec("core", "本月核心结论", b)

    parts = build_summary_cards(data.get("month_cards", []))
    for key, h3 in (("weekly_arc_table", "四周脉络"),
                    ("index_review_table", "指数月度复盘"),
                    ("sector_rank_table", "板块月度排名")):
        if (data.get(key) or {}).get("rows"):
            parts += f"<h3>{h3}</h3>" + build_table(data[key])
    if data.get("market_note"):
        parts += build_split_callout(data["market_note"])
    if parts:
        sec("market", "一、本月行情", parts)

    tr = ""
    for key, h3 in (("trade_stats_table", "分口径统计（全月）"),
                    ("best_worst_table", "最大盈亏各5笔")):
        if (data.get(key) or {}).get("rows"):
            tr += f"<h3>{h3}</h3>" + build_table(data[key])
    if tr:
        if data.get("trade_review_note"):
            tr += build_split_callout(data["trade_review_note"], label="", kind="co-warn")
        sec("trades", "二、交易复盘（全月）", tr)

    if (data.get("system_recon_table") or {}).get("rows"):
        b = build_table(data["system_recon_table"])
        if data.get("system_recon_note"):
            b += build_split_callout(data["system_recon_note"])
        sec("system", "三、系统对账", b)

    if data.get("framework_changes"):
        b = build_iterations(data["framework_changes"])
        if data.get("framework_note"):
            b += build_split_callout(data["framework_note"], label="", kind="co-method")
        sec("framework", "四、本月框架进化总账", b)

    cv = ""
    for key, label, kind in (("cv_aligned", "本月被验证的", "co-good"),
                             ("cv_split", "本月被推翻的", "co-warn"),
                             ("cv_conclusion", "带进下月的判断规则", "co-method")):
        if data.get(key):
            cv += build_split_callout(data[key], label=label, kind=kind)
    if cv:
        sec("crossval", "五、月度校验", cv)

    nx = ""
    if (data.get("next_month_watch_table") or {}).get("rows"):
        nx += "<h3>下月监控清单</h3>" + build_table(data["next_month_watch_table"])
    if data.get("next_month_plan"):
        nx += '<ol class="outlook-list">' + "".join(
            f"<li>{rich(x)}</li>" for x in data["next_month_plan"]) + "</ol>"
    if data.get("stance_one_liner"):
        nx += build_split_callout(data["stance_one_liner"], label="核心立场", kind="co-method")
    if nx:
        sec("nextmonth", "六、下月计划", nx)

    # 2026-08-10：四处渲染器都直接 esc(footer)，而 assemble 侧一直写的是 list——
    # 结果页脚被打印成 Python 的 list repr（['LongPort OpenAPI', ...]）。
    # 四个报告类型全中，没人报过：页脚没人看，正是「无反馈回路」那类静默缺陷。
    footer = data.get("footer_sources", "")
    if isinstance(footer, (list, tuple)):
        footer = " · ".join(str(x) for x in footer)
    if isinstance(footer, list):
        footer = " · ".join(footer)
    return f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(month)} 月总结｜{esc(title)}</title>
<style>
{CSS_PATH.read_text(encoding="utf-8")}
</style>
</head>
<body data-report-type="monthly"><main class="wrap">
<header>
  <div class="eyebrow">美股月总结 · {esc(month)} · {esc(generated_at)}</div>
  <h1>{esc(title)}</h1>
  {f'<p class="muted note">{rich(subtitle)}</p>' if subtitle else ''}
  {f'<div class="badges">{badges}</div>' if badges else ''}
</header>
{build_toc(toc)}
{''.join(body)}
<footer class="source"><p>{esc(footer)}</p></footer>
</main></body>
</html>
"""


RENDERERS = {"premarket": render_premarket, "postmarket": render_postmarket,
             "weekly": render_weekly, "monthly": render_monthly}




# ---------------------------------------------------------------------------
# 字段校验（2026-07-28 Vic要求：写错键名直接报错，不要静默渲染成空）
#
# 起因：playbook_scenarios 的渲染器读 title/trigger/action/target，而组装侧一直写
# scenario/detail——渲染器 .get() 拿不到就填空串，HTML照样生成，情景标题和触发条件
# 在历史报告里一直是空白的，没人发现。同类问题当天还发现一起（盘后 sector_table_note
# 渲染层没接）。两起都是"静默丢失"：数据写了、报告出了、内容没了。
#
# 这里不手写 schema——手写的表会跟渲染器漂移，几周后又是同样的坑。改成**从 builder
# 源码自动推导**它实际读哪些键（扫 .get("k") 和 x["k"]），数据里出现推导集合之外的键
# 就报错。渲染器改了键名，校验表跟着自动改，不需要维护第二份真相。
# ---------------------------------------------------------------------------

_KEY_GET = re.compile(r"""\.get\(\s*['"](\w+)['"]""")
_KEY_IDX = re.compile(r"""\b[a-z_][a-z0-9_]{0,7}\[\s*['"](\w+)['"]\s*\]""")


def _expected_keys(fn) -> set:
    """扫 builder 源码，得出它实际会读的键名集合。"""
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return set()
    return set(_KEY_GET.findall(src)) | set(_KEY_IDX.findall(src))


# JSON字段 → 渲染它的builder。list_of_dicts=True 表示该字段是 [ {...}, ... ]
VALIDATED_FIELDS = {
    "playbook_scenarios": (build_playbook_scenarios, True),
    "premarket_movers": (build_premarket_movers, True),
    "recon_ledger": (build_recon_ledger, True),
    "watchlist_a": (build_watchlist_a, True),
    "defensive_basket": (build_defensive_basket, True),
    "risk_checklist": (build_risk_bars, True),
    "gate_scoreboard_rows": (build_gate_scoreboard, True),
    "scoreboard_rows": (build_scoreboard_table, True),
    "atr_extension_table": (build_atr_extension_table, True),
    "catalyst_watch": (build_catalyst_watch, True),
    "squeeze_candidates": (build_squeeze_table, True),
    "event_gap_candidates": (build_event_gap_table, True),
    "iterations": (build_iterations, True),
    "ml_leaders": (build_ml_leaders_postmarket, True),
    "close_summary_cards": (build_summary_cards, True),
    "gate_scoreboard_rows": (build_gate_scoreboard, True),
    "cross_check": (build_cross_check, False),
    "week_calendar": (build_week_calendar, False),
}


def validate_data(data: dict) -> list:
    """返回错误信息列表；空列表=通过。只查键名拼写，不查取值内容。"""
    errors = []
    for field, (builder, is_list) in VALIDATED_FIELDS.items():
        val = data.get(field)
        if not val:
            continue
        exp = _expected_keys(builder)
        if not exp:                       # 推导不出来就不拦（builder可能是纯位置参数）
            continue
        items = val if is_list else [val]
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            unknown = {k for k in it if not k.startswith("_")} - exp
            missing = exp - set(it)
            # 只在"有未知键"且"同时有期望键没填"时报错——这两件事同时成立，才说明
            # 是把某个键的名字写错了。只多带几个键（如helper自带的诊断字段、渲染器
            # 后来删掉的列）而期望键一个不缺，是无害的，不拦。
            if unknown and missing:
                errors.append(
                    f"{field}[{i}]: 未知键 {sorted(unknown)}，"
                    f"同时缺 {sorted(missing)} —— 是不是把它们写成了前者？"
                    f"（{builder.__name__} 只读 {sorted(exp)}）"
                )
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path", help="path to a report data JSON file")
    parser.add_argument("--no-validate", action="store_true",
                        help="跳过字段名校验（默认校验，发现未知键即报错退出）")
    parser.add_argument("--type", choices=["premarket", "postmarket"], help="report type (default: read from JSON's report_type field, fallback premarket)")
    parser.add_argument("--out", help="output html path (default: output/<type>/<date>-<type>.html)")
    args = parser.parse_args()

    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))

    if not args.no_validate:
        errs = validate_data(data)
        if errs:
            print("字段名校验未通过——这些内容会被静默渲染成空白，已拦下：", file=sys.stderr)
            for e in errs:
                print("  ✗ " + e, file=sys.stderr)
            print("\n改对键名后重跑；确实要先出报告就加 --no-validate。", file=sys.stderr)
            sys.exit(1)

    report_type = args.type or data.get("report_type", "premarket")
    renderer = RENDERERS[report_type]
    html_out = renderer(data)

    if args.out:
        out_path = Path(args.out)
    else:
        if report_type == "monthly":
            out_path = ROOT / "output" / "monthly" / f"{data.get('month','output')}-monthly.html"
        elif report_type == "weekly":
            # 周报文件名是 YYYY-Www-weekly.html（build_index._scan_weekly 按这个模式扫）
            out_path = ROOT / "output" / "weekly" / f"{data.get('week','output')}-weekly.html"
        else:
            date = data.get("date", "output")
            out_path = ROOT / "output" / report_type / f"{date}-{report_type}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    print(f"Wrote {out_path}")

    # 每次生成报告后自动刷新本地索引页
    try:
        import build_index
        idx = build_index.build()
        print(f"Refreshed index {idx}")
    except Exception as e:
        print(f"(index refresh skipped: {e})")

    # 2026-07-28 Vic：「今日定稿后，你增加QA吧，每天不要漂移格式啊」——挂在渲染后自动跑，
    # 不靠人记得去跑。QA不阻断出报告（文件已写好），但会把漂掉的地方直接打在屏幕上。
    if not args.no_validate:
        try:
            import qa_report
            qa_report.run(out_path, Path(args.json_path))
        except Exception as e:
            print(f"(QA skipped: {e})")


if __name__ == "__main__":
    main()
