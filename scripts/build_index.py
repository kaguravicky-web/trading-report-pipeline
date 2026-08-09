#!/usr/bin/env python3
"""Scan output/{premarket,postmarket,weekly,monthly,special} and build output/index.html —
Vic 的每日入口页。

2026-08-04 Vic：「我喜欢老师那样，所有报告按日期排，混在一起，上面的标签已经够我用来分开看了」——
不再按类型分节，全部报告合并成一条按日期倒序的时间线；顶部标签变成筛选器（全部/专题/盘前/盘后/
周报/月报），点一下只看那一类。每张卡片直接复用报告 header 里已有的标题、一句话小结和 badges，
不额外维护摘要。样式复用 templates/report.css，索引专用样式单独注入，配色沿用红绿二色规则。

2026-08-05 Vic：
1) 头部「· D:\\交易为生」和说明段（「盘前、盘后...此页每次生成报告时自动刷新」）没有信息量，删除。
2) 盘前/盘后/周报/月报本质是同一种报告，标签颜色统一（不再分蓝/绿/灰三色），只有专题单独一色。
3) 筛选标签同理合并：盘前/盘后/周报/月报共用一个「报告」筛选按钮，专题单独一个，不再拆四个。
4) 报告预览的灰字摘要经常抓到无意义的占位句（如「待Vic确定新的Market Leader名单后开始追踪」）——
   盘前报告改为直接抓「机会扫描」候选表里的 A 级名单（<tr class="row-group">A级...）显示为
   「今日 Setup A级：XXX」，一眼看到当天有没有A级候选；抓不到这个新格式表格的旧报告维持原摘要逻辑。
5)「其他站点」从页面底部固定区块改成一个筛选标签（「其他」），点了才显示，不再常驻占位置。

2026-08-05 Vic 追加修复：
6) 「其他」标签点了之后专题报告还是混在里面——根因是 #rpt-panel 同时有 class="rpt-list"，
   .rpt-list{display:flex} 这条作者样式盖过了 hidden 属性自带的 UA 样式 [hidden]{display:none}
   （同源层级作者样式恒赢，跟选择器优先级无关）。加一条 #rpt-panel[hidden]{display:none} 用 ID
   选择器的优先级把它压回去。
7)「报告」筛选标签改名「日报」。

2026-08-05 Vic：「上个月的日报可以归档，保留周报月报」——盘前/盘后按月滚动：只有当月的留在主
时间线，更早的收进新的「归档」筛选标签（默认隐藏，点了才展开）；周报/月报不受影响，永远都在。
「当月」以数据里最新一条盘前/盘后的年月为准，不依赖系统时钟，避免服务器时区/时钟漂移导致误判。

Usage:
    python build_index.py
"""
import datetime
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "templates" / "report.css"
OUT = ROOT / "output"

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 类型定义：key -> (中文名, 同日排序优先级)
KINDS = {
    "premarket": ("盘前", 0),
    "postmarket": ("盘后", 1),
    "special": ("专题", 2),
    "weekly": ("周报", 3),
    "monthly": ("月报", 4),
}

# 筛选分组：盘前/盘后/周报/月报是同一种「报告」，只有专题单独一组
GROUP_OF = {
    "premarket": "report",
    "postmarket": "report",
    "weekly": "report",
    "monthly": "report",
    "special": "special",
}
GROUPS = (("report", "日报"), ("special", "专题"))

EXTRA_CSS = """
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
header .badges{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}

/* 顶部筛选标签：沿用 .toc 的 chrome 标签页外观，改成按类型过滤 */
.filters{position:sticky;top:0;z-index:20;display:flex;gap:3px;overflow-x:auto;
  padding:8px 10px 0;margin-bottom:20px;background:#fff;
  border-bottom:1px solid var(--line);box-shadow:0 6px 14px rgba(15,23,42,.05)}
.filters::-webkit-scrollbar{height:0}
.fbtn{flex:0 0 auto;position:relative;bottom:-1px;padding:7px 14px;cursor:pointer;
  color:var(--muted);font-size:12.5px;font-weight:600;font-family:inherit;white-space:nowrap;
  background:#f4f5f7;border:1px solid var(--line);border-radius:9px 9px 0 0}
.fbtn b{margin-left:5px;font-weight:800;font-variant-numeric:tabular-nums}
.fbtn:hover{background:#fff;color:var(--blue)}
.fbtn.is-active{background:#fff;color:var(--blue);border-bottom-color:#fff}

.rpt-list{display:flex;flex-direction:column;gap:10px}
#rpt-panel[hidden],#other-panel[hidden],#archive-panel[hidden]{display:none}
.rpt{display:flex;align-items:flex-start;gap:16px;background:var(--panel);
  border:1px solid var(--line);border-radius:14px;padding:16px 18px;
  box-shadow:0 8px 20px rgba(15,23,42,.04);transition:box-shadow .15s ease,border-color .15s ease}
.rpt:hover{box-shadow:0 14px 32px rgba(15,23,42,.09);border-color:#c3d6f5}
.rpt[hidden]{display:none}
.rpt-body{flex:1;min-width:0}
.rpt-head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.rpt-type{font-size:12.5px;font-weight:800;letter-spacing:.04em;border-radius:999px;
  padding:2px 9px;border:1px solid transparent;white-space:nowrap}
.t-premarket,.t-postmarket,.t-weekly,.t-monthly{color:var(--blue);background:var(--blue-bg);border-color:#c3d6f5}
.t-special{color:#5b4a8a;background:#efecf8;border-color:#d5cdea}
.rpt-date{font-size:12.5px;font-weight:700;color:var(--muted);font-variant-numeric:tabular-nums}
.rpt h3{margin:0 0 5px;font-size:16.5px;line-height:1.42}
.rpt h3 a{color:var(--text)}
.rpt h3 a:hover{color:var(--blue);text-decoration:none}
.rpt-sum{margin:0;font-size:12.5px;line-height:1.7;color:var(--muted)}
.rpt-sum strong{color:var(--text)}
.rpt .badges{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}
.rpt-act{flex:0 0 auto}
.btn{display:inline-block;padding:7px 14px;border-radius:9px;font-size:12.5px;font-weight:700;
  color:#fff;background:var(--blue);border:1px solid var(--blue);white-space:nowrap}
.btn:hover{text-decoration:none;opacity:.9}
.btn.ghost{color:var(--blue);background:#fff}

.idx-links{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:14px 0 0}
.idx-link{display:block;background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:14px 16px;box-shadow:0 8px 20px rgba(15,23,42,.04);color:inherit;
  transition:box-shadow .15s ease,border-color .15s ease}
.idx-link:hover{box-shadow:0 14px 32px rgba(15,23,42,.10);border-color:#c3d6f5;text-decoration:none}
.idx-link strong{display:block;font-size:15px;margin-bottom:3px;color:var(--text)}
.idx-link span{display:block;font-size:12.2px;color:var(--muted);line-height:1.6}
@media(max-width:820px){.idx-links{grid-template-columns:1fr}}
@media(max-width:640px){.rpt{flex-direction:column;gap:10px}.rpt-act{align-self:flex-start}}
"""

FILTER_JS = """
(function(){
  var GROUP = %(group)s;
  var btns = document.querySelectorAll('.fbtn');
  var rpts = document.querySelectorAll('#rpt-panel .rpt');
  var panelEls = {
    rpt: document.getElementById('rpt-panel'),
    archive: document.getElementById('archive-panel'),
    other: document.getElementById('other-panel')
  };
  var TARGET = { all: 'rpt', report: 'rpt', special: 'rpt', archive: 'archive', other: 'other' };
  btns.forEach(function(b){
    b.addEventListener('click', function(){
      var f = b.dataset.filter;
      btns.forEach(function(x){ x.classList.toggle('is-active', x === b); });
      var target = TARGET[f] || 'rpt';
      Object.keys(panelEls).forEach(function(k){
        if (panelEls[k]) panelEls[k].hidden = (k !== target);
      });
      if (target === 'rpt') {
        rpts.forEach(function(r){ r.hidden = (f !== 'all' && GROUP[r.dataset.type] !== f); });
      }
    });
  });
})();
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _pick(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.S)
    return m.group(1).strip() if m else ""


def _plain_title(text: str) -> str:
    """标题：优先 <h1>，退回 <title>，去掉「｜日期」后缀，去掉内嵌标签。
    卡片本身已经用 rpt-date 显示日期+星期，标题里再带一遍「YYYY-MM-DD（周X）」是重复信息
    （比如没跑完整段2那天机器只给了个占位标题「盘前简报 2026-07-31（周五）」）——统一把日期和
    星期几从标题里摘掉，剩下有内容的部分保留，纯占位的就只剩「盘前简报」这类干净短标题。"""
    raw = _pick(r"<h1[^>]*>(.*?)</h1>", text) or _pick(r"<title>(.*?)</title>", text)
    title = re.split(r"[｜|]", re.sub(r"<[^>]+>", "", raw))[0].strip()
    title = re.sub(r"[\s·]*\d{4}-\d{2}-\d{2}\s*（周[一二三四五六日]）", "", title)
    title = re.sub(r"^\d{4}-\d{2}-\d{2}\s*", "", title)
    title = re.sub(r"（周[一二三四五六日]）", "", title)
    title = re.sub(r"^[\s·:：]+|[\s·:：]+$", "", title)
    return title.strip()


def _setup_a_tickers(text: str) -> str:
    """从「机会扫描」候选表里抓 A 级（允许执行）分组的 TICKER 列表，逗号分隔的直接原样保留。"""
    m = re.search(
        r'<tr class="row-group"><td colspan="7">A级[^<]*</td></tr>(.*?)(?=<tr class="row-group"|</tbody>)',
        text, re.S,
    )
    if not m:
        return ""
    cells = re.findall(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>", m.group(1), re.S)
    tickers = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
    return "、".join(t for t in tickers if t)


def _header_bits(text: str, kind: str = "") -> tuple:
    """从报告 header 里取一句话小结和 badges；专题报告没有 header note 就退回 meta description。
    盘前报告改抓机会扫描候选表的 A 级名单，比 header 摘要更能一眼看出当天有没有可执行的setup。"""
    header = _pick(r"<header[^>]*>(.*?)</header>", text)
    badges = _pick(r'<div class="badges">(.*?)</div>', header)

    if kind == "premarket" and re.search(r"允许执行|观察为主|当日忽略", text):
        a_list = _setup_a_tickers(text)
        summary = f"今日 Setup A级：{esc(a_list)}" if a_list else "今日无 Setup A级候选"
        return summary, badges

    summary = _pick(r'<p class="muted note">(.*?)</p>', header)
    if not summary:
        # 专题报告没有统一的 header note：先用 meta description，再退回正文第一段
        summary = html.escape(_pick(r'<meta name="description" content="(.*?)"', text))
    if not summary:
        first_p = _pick(r"<p[^>]*>(.*?)</p>", text[text.find("<body"):])
        summary = html.escape(re.sub(r"<[^>]+>", "", first_p))[:180]
    return summary, badges


def _weekday(d: datetime.date) -> str:
    return WEEKDAYS[d.weekday()]


def _entry(path: Path, kind: str, sort_date: datetime.date, label: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    summary, badges = _header_bits(text, kind)
    return {
        "kind": kind,
        "sort": (sort_date, KINDS[kind][1]),
        "label": label,
        "file": f"{path.parent.name}/{path.name}",
        "title": _plain_title(text),
        "summary": summary,
        "badges": badges,
    }


def collect() -> list:
    """把五类报告合并成一条按日期倒序的时间线。"""
    items = []

    for kind in ("premarket", "postmarket"):
        for f in (OUT / kind).glob(f"*-{kind}.html") if (OUT / kind).exists() else []:
            m = re.match(r"(\d{4}-\d{2}-\d{2})-", f.name)
            if not m:
                continue
            d = datetime.date.fromisoformat(m.group(1))
            items.append(_entry(f, kind, d, f"{m.group(1)} {_weekday(d)}"))

    if (OUT / "special").exists():
        for f in (OUT / "special").glob("*.html"):
            m = re.match(r"(\d{4}-\d{2}-\d{2})-", f.name)
            if not m:
                continue
            d = datetime.date.fromisoformat(m.group(1))
            items.append(_entry(f, "special", d, f"{m.group(1)} {_weekday(d)}"))

    if (OUT / "weekly").exists():
        for f in (OUT / "weekly").glob("*-weekly.html"):
            m = re.match(r"(\d{4})-W(\d{2})-", f.name)
            if not m:
                continue
            # 周报排在该 ISO 周的周五，跟当周盘后报告落在同一区间
            d = datetime.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 5)
            items.append(_entry(f, "weekly", d, f"{m.group(1)}-W{m.group(2)}"))

    if (OUT / "monthly").exists():
        for f in (OUT / "monthly").glob("*-monthly.html"):
            m = re.match(r"(\d{4})-(\d{2})-", f.name)
            if not m:
                continue
            y, mo = int(m.group(1)), int(m.group(2))
            nxt = datetime.date(y + (mo == 12), (mo % 12) + 1, 1)
            items.append(_entry(f, "monthly", nxt - datetime.timedelta(days=1), f"{m.group(1)}-{m.group(2)}"))

    # 日期倒序，但同一天内按类型正序（盘前→盘后→专题→周报→月报），所以优先级取负号
    items.sort(key=lambda x: (x["sort"][0].toordinal(), -x["sort"][1]), reverse=True)
    return items


def _card(it: dict) -> str:
    name = KINDS[it["kind"]][0]
    badges = f'<div class="badges">{it["badges"]}</div>' if it["badges"] else ""
    summary = f'<p class="rpt-sum">{it["summary"]}</p>' if it["summary"] else ""
    return (
        f'<article class="rpt" data-type="{esc(it["kind"])}">'
        '<div class="rpt-body">'
        f'<div class="rpt-head"><span class="rpt-type t-{esc(it["kind"])}">{esc(name)}</span>'
        f'<span class="rpt-date">{esc(it["label"])}</span></div>'
        f'<h3><a href="{esc(it["file"])}">{esc(it["title"])}</a></h3>'
        f'{summary}{badges}</div>'
        f'<div class="rpt-act"><a class="btn" href="{esc(it["file"])}">打开报告</a></div>'
        '</article>'
    )


def _daily_archive_cutoff(items: list):
    """当月以数据里最新一条盘前/盘后为准（不依赖系统时钟），更早的盘前/盘后进归档。"""
    daily_dates = [i["sort"][0] for i in items if i["kind"] in ("premarket", "postmarket")]
    if not daily_dates:
        return None
    latest = max(daily_dates)
    return (latest.year, latest.month)


def _filters(items: list, archived_count: int = 0) -> str:
    counts = {k: sum(1 for i in items if i["kind"] == k) for k in KINDS}
    btns = [f'<button class="fbtn is-active" type="button" data-filter="all">全部 <b>{len(items)}</b></button>']
    for gkey, gname in GROUPS:
        gcount = sum(counts[k] for k, v in GROUP_OF.items() if v == gkey)
        if gcount:
            btns.append(f'<button class="fbtn" type="button" data-filter="{gkey}">{gname} <b>{gcount}</b></button>')
    if archived_count:
        btns.append(f'<button class="fbtn" type="button" data-filter="archive">归档 <b>{archived_count}</b></button>')
    btns.append('<button class="fbtn" type="button" data-filter="other">其他</button>')
    return f'<nav class="filters" aria-label="按类型筛选">{"".join(btns)}</nav>'


def _archive_section(archived: list) -> str:
    if not archived:
        return ""
    cards = "".join(_card(i) for i in archived)
    return (
        '<section id="archive-panel" class="rpt-list" hidden>'
        '<p class="muted" style="margin:0 0 12px">已归档：本月之前的盘前/盘后。'
        '周报/月报不受影响，一直留在「日报」里。</p>'
        f'{cards}</section>'
    )


def _links_section() -> str:
    links = [
        ("tradebook.html", "📒 TradeBook 交易日志", "每笔进出、持有理由与止损的台账", ""),
        ("https://kaguravicky-web.github.io/earnings/", "📊 财报深度分析归档",
         "基本面深度 + 市场解读一致性判断", ' target="_blank" rel="noopener"'),
        ("https://kaguravicky-web.github.io/options/", "📈 期权流分析框架",
         "期权流与 Gamma 判据", ' target="_blank" rel="noopener"'),
    ]
    cards = "".join(
        f'<a class="idx-link" href="{esc(href)}"{attr}><strong>{esc(name)}</strong>'
        f'<span>{esc(desc)}</span></a>'
        for href, name, desc, attr in links
    )
    return (
        '<section id="other-panel" hidden><h2 style="margin-top:30px">其他站点</h2>'
        f'<div class="idx-links">{cards}</div></section>'
    )


def build() -> Path:
    items = collect()
    cutoff = _daily_archive_cutoff(items)
    archived = [
        i for i in items
        if i["kind"] in ("premarket", "postmarket") and (i["sort"][0].year, i["sort"][0].month) < cutoff
    ] if cutoff else []
    archived_files = {i["file"] for i in archived}
    visible = [i for i in items if i["file"] not in archived_files]

    if not visible:
        body = '<section id="rpt-panel"><p class="placeholder">还没有生成任何报告。跑一次 render_report.py 后回来刷新。</p></section>'
        filters = ""
    else:
        body = f'<section id="rpt-panel" class="rpt-list">{"".join(_card(i) for i in visible)}</section>'
        filters = _filters(visible, len(archived))
    latest_btn = (
        f'<p style="margin:14px 0 0"><a class="btn" href="{esc(items[0]["file"])}">最新报告 →</a></p>'
        if items else ""
    )

    filter_js = FILTER_JS % {"group": json.dumps(GROUP_OF, ensure_ascii=False)}

    html_out = f"""<!doctype html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>交易报告索引</title>
<style>
{CSS_PATH.read_text(encoding="utf-8")}
{EXTRA_CSS}
</style>
</head>
<body data-report-type="index"><main class="wrap">
<header>
  <div class="eyebrow">交易报告索引</div>
  <h1>美股监控报告</h1>
  {latest_btn}
</header>
{filters}
{body}
{_archive_section(archived)}
{_links_section()}
<footer class="source"><p>本地索引页，无需 GitHub。用浏览器打开本文件即可作为每日入口。</p></footer>
</main>
<script>{filter_js}</script>
</body>
</html>
"""
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "index.html"
    out_path.write_text(html_out, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    p = build()
    print(f"Wrote {p}")
