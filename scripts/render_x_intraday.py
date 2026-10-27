#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X 盘中简报（xdesk）渲染器 —— 2026-08-20 建。

**为什么有这个东西**：Vic 2026-08-20：「我的盘前盘后报告的 x 台账，我想做成当天内
可以随时翻阅、1-2 小时的单独总结，聊天窗口也可以，但是要抓的多一点，希望能看到图」。

在此之前 X 观点池只在盘前跑一次，结论被压进报告里的一个 callout；盘中想再看只能
临时加一段 `delta_scan`（8/19 手工干过一次）。现在正式化成一个独立产物：

  - **一天一页**：`output/xdesk/YYYY-MM-DD-x.html`，同一天多轮扫描**追加**进同一页，
    最新一轮在最上面。当天任何时候打开都是当天全部内容，不用翻聊天记录。
  - **带图**：帖子里的图（trader 的 K 线标注、Deepvue 截图、宏观图表）按 URL 提取后
    **下载到本地** `output/xdesk/media/`，页面直接显示。这不违反「X 扫描不截图」那条
    省 token 规则——规则禁的是让模型去 *看* 截图（贵），这里模型只搬 URL 字符串（几乎不要钱），
    图是渲染时由 Python 下载、由浏览器显示给 Vic 看的，模型全程没读过图像。
  - **增量**：每轮只覆盖「距上一轮到现在」的新帖，靠 tweet url 去重，跨轮不重复展示。

输入：`data/cache/x_intraday_YYYYMMDD.json`（格式见 templates/x_intraday_schema.md）
输出：`output/xdesk/YYYY-MM-DD-x.html` + `output/xdesk/index.html`（按天倒序的入口页）

用法：
    python scripts/render_x_intraday.py                 # 渲染今天
    python scripts/render_x_intraday.py --date 2026-08-20
    python scripts/render_x_intraday.py --no-media      # 跳过图片下载（只引用远端 URL）
"""
import argparse
import datetime
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "templates" / "report.css"
CACHE = ROOT / "data" / "cache"
OUTDIR = ROOT / "output" / "xdesk"

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 条目分类 -> (中文名, badge class)
KINDS = {
    "macro":    ("宏观", "blue"),
    "stock":    ("个股", "green"),
    "congress": ("国会", "amber"),
    "cramer":   ("反指", "red"),
    "13f":      ("13F", "blue"),
    "ep":       ("EP候选", "green"),
    "other":    ("其他", "blue"),
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


# ---------------------------------------------------------------- 图片本地化

def normalize_media_url(src):
    """把 X 的缩略图 URL 归一到 medium 尺寸。

    X 给的 src 常带 `?format=jpg&name=small`（360px，K 线图上的价格看不清）。
    换成 name=medium（1200px 上限）——large/orig 对 K 线图没有额外信息量但体积翻倍。
    """
    if "pbs.twimg.com" not in src:
        return src
    src = re.sub(r"([?&]name=)(small|thumb|900x900|large|orig)", r"\1medium", src)
    if "name=" not in src:
        src += ("&" if "?" in src else "?") + "name=medium"
    return src


def is_content_image(src):
    """排除头像/表情/站点图标，只留帖子正文里的图。"""
    if not src or "pbs.twimg.com" not in src:
        return False
    bad = ("profile_images", "profile_banners", "/emoji/", "abs.twimg.com",
           "card_img/logo", "semantic_core_img")
    return not any(b in src for b in bad)


def download_media(src, date, timeout=20):
    """下载一张图到 output/xdesk/media/YYYYMMDD/。

    返回相对 HTML 的路径；失败返回 None（调用方回落到远端 URL——X 的 media CDN
    是公开的，不带图也能在有网时显示，只是隔天回看有失效风险）。
    """
    src = normalize_media_url(src)
    day = date.replace("-", "")
    d = OUTDIR / "media" / day
    d.mkdir(parents=True, exist_ok=True)
    ext = ".png" if "format=png" in src else ".jpg"
    name = hashlib.sha1(src.encode("utf-8")).hexdigest()[:16] + ext
    fp = d / name
    rel = "media/%s/%s" % (day, name)
    if fp.exists() and fp.stat().st_size > 0:
        return rel
    try:
        req = urllib.request.Request(src, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
        if len(blob) < 512:          # 太小基本是占位图/错误页
            return None
        fp.write_bytes(blob)
        return rel
    except Exception as e:
        print("  [media] 下载失败 %s… (%s)" % (src[:70], e), file=sys.stderr)
        return None


# ---------------------------------------------------------------- 小工具

def esc(s):
    return html.escape(str(s or ""))


def linkify(text):
    """转义后把 $TICKER 和 @handle 变成可视化 chip，外链留成纯文本。

    🔴 不把帖子里的外部链接渲染成可点击的 <a>——CONTEXT.md「X 扫描注意事项」：
    不点帖子里的外链（尤其短链）。渲染成纯文本 Vic 想查还是能复制，但不会手滑点进去。
    """
    t = esc(text)
    # **加粗** 转成 <b>：不转的话字面 ** 会漏到页面上（QA 第 4 条抓的就是这个）
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w/])\$([A-Za-z]{1,6})\b", r'<b class="tk">$\1</b>', t)
    t = re.sub(r"(?<![\w/])@([A-Za-z0-9_]{2,15})\b", r'<span class="hd">@\1</span>', t)
    return t.replace("\n", "<br>")


def sgt_from_utc(utc_iso):
    """ISO UTC 时间戳 -> (SGT HH:MM, 完整 SGT 字符串)。X 的 <time datetime> 是 UTC。"""
    if not utc_iso:
        return ("", "")
    try:
        s = str(utc_iso).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        sgt = dt.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        return (sgt.strftime("%H:%M"), sgt.strftime("%m-%d %H:%M SGT"))
    except Exception:
        return (str(utc_iso)[:16], str(utc_iso))


def tickers_of(item):
    """条目的 ticker 字段可能是 'ADI' / 'LITE/MTSI/AAOI' / '—' / 列表。"""
    v = item.get("ticker")
    if not v:
        return []
    raw = v if isinstance(v, list) else re.split(r"[/,、\s]+", str(v))
    out = []
    for t in raw:
        t = str(t).strip().lstrip("$").upper()
        if t and t not in ("—", "-", "无", "N/A") and re.fullmatch(r"[A-Z.]{1,6}", t):
            out.append(t)
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 渲染

EXTRA_CSS = """
.xhead{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}

.filters{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;gap:6px;
  padding:10px 0;margin-bottom:14px;background:linear-gradient(180deg,#fbfbfd 70%,rgba(251,251,253,0))}
.filters button{font:inherit;font-size:13px;font-weight:700;cursor:pointer;padding:6px 13px;
  border-radius:999px;border:1px solid var(--line);background:var(--panel);color:var(--muted)}
.filters button.on{background:var(--blue);border-color:var(--blue);color:#fff}

/* 🔤 2026-08-23 Vic：「x 的也没对齐」。跟索引页同一个病：
   顶部 callout 来自 report.css 的 max-width:calc(--measure + 12em) = 850px，
   而推文卡片 .tw 没限宽，撑满 1160 容器的 1120px —— **同一页两种盒子宽度**。
   修法跟索引页一致：**限宽收在容器上，让所有盒子共用一条边**，不给盒子各自限宽。
   算式：wrap 780 − padding 40 = 740 一条边；callout 取 min(850,740)=740，
   推文卡片也是 740；卡片正文 = 740 − 32 padding − 62 时间列 − 14 gap = 632px，
   14.5px 字号 → 每行约 43 字。 */
/* 2026-08-23 Vic：「现在改 x 盘中和盘前」——跟报告统一，不再单独收窄到 780。
   容器由 report.css 的 .wrap{max-width:1200px} 定，所有盒子铺满，左右都对齐。 */

.run{margin:0 0 26px}
.run-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;padding:11px 16px;
  background:#e7ecf3;border:1px solid #d5dde7;border-radius:12px;margin-bottom:12px}
.run-bar b{font-size:16px;color:#2c3e55}
.run-bar small{color:var(--muted);font-size:12.5px}

.tw{display:flex;gap:14px;background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:14px 16px;margin-bottom:10px;box-shadow:0 8px 20px rgba(15,23,42,.04)}
.tw.hot{border-left:5px solid var(--red)}
.tw.pick{border-left:5px solid var(--green)}
.tw .when{flex:0 0 62px;color:var(--muted);font-size:12.5px;font-variant-numeric:tabular-nums;
  font-weight:700;line-height:1.35}
.tw .when i{display:block;font-style:normal;font-weight:600;font-size:11px;opacity:.75}
.tw .body{flex:1;min-width:0}
.tw .meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:6px}
.tw .who{font-weight:800;font-size:14px}
.tw .txt{font-size:14.5px;line-height:1.6}
.tw .txt .tk{color:var(--blue);font-weight:800}
.tw .txt .hd{color:var(--muted)}
.tw .src{display:block;margin-top:7px;font-size:12px;color:var(--muted);word-break:break-all}
.demote{opacity:.72}

.chip{display:inline-flex;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:800;
  border:1px solid transparent;line-height:1.5}
.chip.tk{color:var(--blue);background:var(--blue-bg);border-color:#c3d6f5}
.chip.new{color:var(--green);background:var(--green-bg);border-color:#bfe0cd}
.chip.late{color:#8a5a00;background:#fff4e0;border-color:#f0d9a8}

.shots{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
/* flex:0 0 auto 是必须的：默认的 flex-shrink 会在手机宽度下把并排的两张图
   一路压到 min-width（实测压成 120px 宽，K 线图完全没法看）。禁止收缩之后
   放不下就换行，这才是想要的行为。*/
.shots a{flex:0 0 auto;display:block;line-height:0;max-width:100%;
  border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#f0f2f6}
/* 竖图（Kobeissi 那种长条信息图）按 max-height 缩会变成一条很窄的缩略图，
   所以多图卡片也给到 320px，单图 460px；真要看细节点开灯箱看原图。*/
.shots img{max-height:320px;max-width:100%;width:auto;height:auto;display:block;cursor:zoom-in}
.shots.solo img{max-height:460px}

/* 手机：时间列收窄、卡片留白减小，把宽度让给正文和图 */
@media(max-width:520px){
  .wrap{padding:16px 10px 40px}
  .tw{gap:10px;padding:12px 12px}
  .tw .when{flex:0 0 46px;font-size:11.5px}
  .tw .txt{font-size:14px}
  .shots img{max-height:260px}
  .shots.solo img{max-height:360px}
}
.miss{font-size:12px;color:var(--muted);padding:8px 10px;border:1px dashed var(--line);
  border-radius:8px;margin-top:8px}

#lb{position:fixed;inset:0;z-index:99;background:rgba(15,23,42,.86);display:none;
  align-items:center;justify-content:center;padding:24px;cursor:zoom-out}
#lb.on{display:flex}
#lb img{max-width:100%;max-height:100%;border-radius:8px}

.cover{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;margin-top:10px}
.cover div{font-size:13px;padding:7px 11px;border:1px solid var(--line);border-radius:9px;
  background:var(--panel);color:var(--muted)}
@media print{.filters,#lb{display:none}}
"""

LB_JS = """
(function(){
  var lb=document.getElementById('lb'), im=lb.querySelector('img');
  document.addEventListener('click',function(e){
    var a=e.target.closest('.shots a');
    if(a){e.preventDefault();im.src=a.getAttribute('href');lb.classList.add('on');return;}
    if(e.target.closest('#lb')){lb.classList.remove('on');im.src='';}
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){lb.classList.remove('on');im.src='';}
  });
  var btns=[].slice.call(document.querySelectorAll('.filters button'));
  btns.forEach(function(b){b.addEventListener('click',function(){
    btns.forEach(function(x){x.classList.remove('on')}); b.classList.add('on');
    var f=b.dataset.f;
    [].forEach.call(document.querySelectorAll('.tw'),function(el){
      var ok = f==='all' ? true
             : f==='img' ? el.dataset.img==='1'
             : f==='hot' ? el.dataset.flag==='hot'
             : el.dataset.kind===f;
      el.style.display = ok ? '' : 'none';
    });
    [].forEach.call(document.querySelectorAll('.run'),function(r){
      var vis=[].slice.call(r.querySelectorAll('.tw')).some(function(el){
        return el.style.display!=='none';});
      r.style.display = vis ? '' : 'none';
    });
  })});
})();
"""


LATE_HOURS = 24     # 发布到送达超过这么久 = 跨轮补录，卡片上打 chip

def _ts(iso):
    """任意带时区的 ISO 串 → aware datetime；解析不了返回 None。"""
    import datetime as _dt
    try:
        t = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return t.replace(tzinfo=_dt.timezone.utc) if t.tzinfo is None else t
    except Exception:
        return None


def _lag_hours(item_utc, run_at):
    """条目从发布到这一轮送达之间隔了多少小时；算不出来返回 None。

    🔴 判据是滞后时长，不是日历日。第一版按美东日比较，结果把「xdesk 文件按新加坡日期命名、
    内容天然是前一个美东日」这个时区差也标成了补录（9/1 那页 112 条标了 59 条），是错的。
    """
    a, b = _ts(item_utc), _ts(run_at)
    if not a or not b:
        return None
    return (b - a).total_seconds() / 3600.0


def render_item(it, date, no_media, run_at=""):
    kind = it.get("kind") or "other"
    kname, kcls = KINDS.get(kind, KINDS["other"])
    # 时间列很窄：主行是时分，副行（<i>）是月日。
    hhmm, full = sgt_from_utc(it.get("utc") or it.get("time_utc"))
    sub = full[:5]
    if it.get("time_approx"):
        # 导进来的条目可能只有「8/18」这种日期、或者根本不是一条推（EP 候选写「归纳」）。
        # 显示原始字串而不是换算出来的 08:00，免得看着像精确时间；副行只标一个「约」。
        hhmm, sub = str(it.get("time") or "")[:8], "约"
    elif not hhmm and it.get("time"):
        hhmm, sub = str(it["time"])[:5], ""
    flag = str(it.get("flag") or "").lower()
    hot = flag in ("hot", "red", "🔴")
    cls = "tw" + (" hot" if hot else " pick" if flag in ("pick", "🎯") else "")
    if it.get("demoted"):
        cls += " demote"

    chips = "".join('<span class="chip tk">$%s</span>' % esc(t) for t in tickers_of(it))
    if it.get("new_to_ledger"):
        chips += '<span class="chip new">未入台账</span>'
    # 2026-09-09 加：跨轮补录标记。Vic 问「$INTC 那条我 9/6 怎么没看到」——
    # 那条发在 9/6 16:11 UTC，比当轮窗口尾巴晚 59 分钟，接着下一轮 Chrome 断线没跑成，
    # 拖到 9/8 才补进来。发布日不等于送达轮，必须在卡片上看得见，不能靠正文里记得写。
    _lag = _lag_hours(it.get("utc"), run_at)
    if _lag is not None and _lag >= LATE_HOURS:
        chips += ('<span class="chip late">补录 · 迟 %d 小时</span>'
                  % round(_lag))

    # 图片：只搬 URL，下载和显示都不经过模型
    cells, failed = [], 0
    for m in (it.get("media") or []):
        src = m if isinstance(m, str) else (m.get("src") or "")
        alt = "" if isinstance(m, str) else (m.get("alt") or "")
        if not is_content_image(src):
            continue
        local = None if no_media else download_media(src, date)
        if local is None and not no_media:
            failed += 1
        remote = normalize_media_url(src)
        href = local or remote
        # 本地优先、远端兜底：`output/xdesk/media/` 没进 git（见 output/.gitignore），
        # 所以本地打开走下载好的副本，GitHub Pages 上那个路径 404，onerror 自动换成
        # X 自己的 CDN。一份 HTML 两处都能看，仓库也不用背每天 1.5MB 的图。
        fb = ""
        if local and remote != local:
            fb = (" onerror=\"this.onerror=null;this.src='%s';"
                  "this.closest('a').href='%s'\"" % (esc(remote), esc(remote)))
        cells.append('<a href="%s"><img src="%s" alt="%s" loading="lazy"%s></a>'
                     % (esc(href), esc(href), esc(alt), fb))
    shots = ""
    if cells:
        shots = '<div class="shots%s">%s</div>' % (" solo" if len(cells) == 1 else "",
                                                   "".join(cells))
    if failed:
        shots += '<div class="miss">%d 张图没抓下来（X 侧失效或超时），原帖里还能看</div>' % failed

    url = it.get("url") or ""
    src_line = '<span class="src">原帖：%s</span>' % esc(url) if url else ""
    body = it.get("summary") or it.get("note") or ""

    return ('<div class="%s" data-kind="%s" data-img="%d" data-flag="%s">\n'
            '  <div class="when">%s<i>%s</i></div>\n'
            '  <div class="body">\n'
            '    <div class="meta"><span class="who">%s</span>'
            '<span class="badge %s">%s</span>%s</div>\n'
            '    <div class="txt">%s</div>\n'
            '    %s%s\n'
            '  </div>\n</div>') % (
        cls, esc(kind), 1 if cells else 0, "hot" if hot else "",
        esc(hhmm), esc(sub),
        esc(it.get("handle") or ""), kcls, kname, chips,
        linkify(body), shots, src_line)


def render_run(run, date, no_media, fallback_id):
    items = run.get("items") or []
    checked = run.get("accounts_checked") or []
    nonew = run.get("accounts_no_new") or []
    ncalls = sum(c.get("tool_calls", 0) for c in (run.get("cost_log") or []))
    at = run.get("run_at") or ""

    # 从盘前/盘后扫描导进来的段用自己的 label（「盘前扫描（导入）」），不叫「第 N 轮」
    title = run.get("label") or ("第 %s 轮" % run.get("run_id", fallback_id))
    bar = ('<div class="run-bar"><b>%s · %s</b><small>窗口 %s</small>'
           '<span style="flex:1"></span>'
           '<small>%d 条 · 查了 %d 号 · %d 号无更新%s</small></div>') % (
        esc(title), esc(at[11:16] or at), esc(run.get("window") or ""),
        len(items), len(checked), len(nonew),
        (" · %d 次调用" % ncalls) if ncalls else "")

    # 🔴 2026-10-15 Vic：「其实我不需要你的x总结，所以总结可以不总结，或者说在每轮最后
    #    才总结宏观」。原来 takeaway 顶在条目上面当「本轮判断」，等于先读一篇综述再读原文；
    #    他要的是条目本身（原话＋核过的价）。现在移到条目之后，且内容只写宏观——
    #    交易员那部分已经在条目里，不在这里重述。位置改在渲染层收口，不靠我记得。
    take = run.get("takeaway")
    tk = '<div class="callout"><b>宏观小结</b><br>%s</div>' % linkify(take) if take else ""

    # 🔴 2026-10-16 Vic：「x 你按时间顺序排，我从上开始读，读到下面都是不想继续刷了」。
    #    以前是按我组装时的顺序渲染 —— 而我是按主题分组写的（PPI / 利率 / CoreWeave /
    #    韩国 / 交易员 / Cramer…），结果他读到一半停下来就整块主题、整个账号全丢了
    #    （Cramer 永远在最底下，不管他是几点说的）。
    #    改成按发布时间升序：停在哪里都只是「这一天读到一半」，不会漏掉整类内容。
    #    收口在渲染层，不靠我组装时记得排。
    #    想换成最新在上只要把 reverse=True 加回来。
    #    次级键用 status id（snowflake 本身就是毫秒级时间戳）——`utc` 字段只精确到分钟，
    #    同一分钟有并列时（实测 121 条里有 8 条）光按 utc 排会保留组装顺序、顺序不确定。
    def _seq(i):
        sid = (i.get("url") or "").rsplit("/", 1)[-1]
        return (i.get("utc") or "", int(sid) if sid.isdigit() else 0)
    items = sorted(items, key=_seq)
    cards = ("\n".join(render_item(it, date, no_media, at) for it in items) if items
             else '<div class="miss">这一轮账号池里没有新的实质内容。</div>')

    cov = ""
    if nonew:
        cov = ('<div class="cover">%s</div>'
               % "".join("<div>%s · 无更新</div>" % esc(h) for h in nonew))
    note = run.get("notes")
    nt = '<div class="note" style="margin-top:8px">%s</div>' % linkify(note) if note else ""
    return '<section class="run">%s%s%s%s%s</section>' % (bar, cards, cov, tk, nt)


# ── 广告／拉客帖闸门（2026-09-25 Vic：「广告帖子以后过滤掉」）──────────────
# 这些号一边发盘面一边卖服务。推销帖占版位、又没有信息量，一律不收录。
# 写成会失败的检查，而不是写进文档——漏掉一条渲染就红。
# 2026-10-20 误报修正：`subscribe` 会匹配进 `oversubscribed` 里面。
#   当天 @zerohedge 写「400x oVerSUbScrIbeD」（韩国最大 IPO 首日 −32%）被判广告、整轮渲染失败。
#   用 (?<!over) 把它挡掉：真正的 CTA「Subscribe below」照样命中，「oversubscribed」放行。
#   不要改成 --allow-promo 了事 —— 那会把整轮的闸门一起关掉。
PROMO_PAT = re.compile(
    r"(7\s*days?\s*free|free\s*trial|trade\s*live\s*with\s*(me|us)"
    r"|join\s*(us|our|the)\s*(team|group|discord|room)|sign\s*up"
    r"|(?<!over)subscribe|promo\s*code|use\s*code|link\s*in\s*bio"
    r"|members?\s*(only|and\s*me|area)|my\s*service|our\s*service"
    r"|mentorship|join\s*the\s*\w+\s*team|turn\s*those\s*losses"
    r"|beating\s*\$?SPX|vs\.?\s*\$?SPX.*(ytd|basis\s*points)"
    r"|tracked\s*24/7|options?\s*flow\s*reviews?"
    r"|coming\s*soo+n|waitlist|early\s*access|webinar|masterclass"
    r"|disclaimer\s*:)",
    re.I)


def promo_hits(runs):
    """返回疑似广告帖 [(handle, url, 命中的词)]。"""
    out = []
    for r in runs:
        for it in (r.get("items") or []):
            blob = " ".join(str(it.get(k) or "") for k in ("full_text", "summary", "quoted"))
            m = PROMO_PAT.search(blob)
            if m:
                out.append((it.get("handle", "?"), it.get("url", "?"), m.group(0)))
    return out


# ── 名单闸门（2026-09-27）──────────────────────────────────────────────
# 名单以前只写在 CONTEXT.md 正文和每轮的一次性脚本里，加人/删人全靠我记得。
# 现在单一来源是 data/x_accounts.json，这里核对每轮的 accounts_checked：
# 少扫一个号就渲染失败，而不是页面上少一行、谁也看不出来。
ROSTER_FILE = ROOT / "data" / "x_accounts.json"


def roster():
    if not ROSTER_FILE.exists():
        return []
    d = json.loads(ROSTER_FILE.read_text(encoding="utf-8"))
    return [a["handle"] for a in d.get("accounts", [])]


def roster_gaps(runs):
    want = {h.lower(): h for h in roster()}
    if not want:
        return []
    out = []
    for r in runs:
        if r.get("label"):          # 盘前/盘后导入的段不按 xdesk 名单要求
            continue
        got = {str(a).lstrip("@").lower() for a in (r.get("accounts_checked") or [])}
        miss = [want[k] for k in sorted(want) if k not in got]
        if miss:
            out.append((r.get("run_id"), miss))
    return out


def build_day(date, no_media=False, allow_promo=False, allow_roster_gap=False):
    src = CACHE / ("x_intraday_%s.json" % date.replace("-", ""))
    if not src.exists():
        raise SystemExit("没有 %s —— 先跑扫描落盘再渲染。" % src)
    d = json.loads(src.read_text(encoding="utf-8"))
    runs = sorted(d.get("runs") or [], key=lambda r: r.get("run_at", ""), reverse=True)

    gaps = roster_gaps(runs)
    if gaps and not allow_roster_gap:
        raise SystemExit(
            "🔴 有轮次没扫全 data/x_accounts.json 的名单——\n%s\n"
            "补扫后再渲染；这一轮确实不打算扫全就加 --allow-roster-gap。"
            % "\n".join("  第 %s 轮少了：%s" % (rid, "、".join(m)) for rid, m in gaps))

    hits = promo_hits(runs)
    if hits and not allow_promo:
        raise SystemExit(
            "🔴 疑似广告／拉客帖 %d 条，不许收录（Vic 2026-09-25）——\n%s\n"
            "从 data/cache 里删掉这些条目再渲染；确实是盘面内容就加 --allow-promo。"
            % (len(hits), "\n".join("  %s %s  ← 命中「%s」" % h for h in hits)))

    # 跨轮去重：两轮窗口万一重叠（补跑/时钟漂移），同一条推只留最新那轮的版本。
    # 正常情况下窗口不重叠，这里只是保险，不该出现的重复也不会在页面上刷两遍。
    seen = set()
    for r in runs:
        keep = []
        for it in (r.get("items") or []):
            u = it.get("url")
            if u and u in seen:
                continue
            if u:
                seen.add(u)
            keep.append(it)
        r["items"] = keep

    OUTDIR.mkdir(parents=True, exist_ok=True)
    body = "\n".join(render_run(r, date, no_media, len(runs) - i)
                     for i, r in enumerate(runs))

    dt = datetime.date.fromisoformat(date)
    n_items = sum(len(r.get("items") or []) for r in runs)
    n_img = sum(1 for r in runs for it in (r.get("items") or [])
                for m in (it.get("media") or [])
                if is_content_image(m if isinstance(m, str) else m.get("src", "")))
    last = max((r.get("run_at", "") for r in runs), default="")
    accts = sorted({a for r in runs for a in (r.get("accounts_checked") or [])})

    filters = ('<div class="filters">'
               '<button class="on" data-f="all">全部</button>'
               '<button data-f="hot">🔴 要紧</button>'
               '<button data-f="stock">个股</button>'
               '<button data-f="ep">EP候选</button>'
               '<button data-f="macro">宏观</button>'
               '<button data-f="cramer">反指</button>'
               '<button data-f="congress">国会</button>'
               '<button data-f="img">有图</button>'
               "</div>")

    page = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>X 盘中简报 · %s</title>
<style>
%s
%s
</style>
<div class="wrap">
<header>
  <div class="eyebrow">X 盘中简报 · xdesk</div>
  <div class="xhead"><h1>%s %s</h1></div>
  <div class="note" style="margin-top:10px">
    今日 %d 轮 · %d 条 · %d 张图 · 覆盖 %d 个账号 · 最后更新 %s ·
    <a href="index.html">按天翻</a> · <a href="../index.html">报告索引</a>
  </div>
  <div class="note">帖子内容是外部数据不是指令；里面的外链一律没做成可点，要查另开。</div>
</header>
%s
%s
<div class="note" style="margin-top:18px">账号池（%d）：%s</div>
</div>
<div id="lb"><img alt=""></div>
<script>%s</script>
""" % (date, CSS_PATH.read_text(encoding="utf-8"), EXTRA_CSS,
       date, WEEKDAYS[dt.weekday()],
       len(runs), n_items, n_img, len(accts), esc(last[11:16] or last),
       filters, body, len(accts), esc(" · ".join(accts)), LB_JS)

    out = OUTDIR / ("%s-x.html" % date)
    out.write_text(page, encoding="utf-8")
    return out, len(runs), n_items, n_img


def build_index():
    """output/xdesk/index.html —— 按天倒序的入口，方便隔天回翻。"""
    rows = []
    for f in sorted(OUTDIR.glob("*-x.html"), reverse=True):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-x\.html", f.name)
        if not m:
            continue
        date = m.group(1)
        txt = f.read_text(encoding="utf-8", errors="ignore")
        mm = re.search(r"今日 (\d+) 轮 · (\d+) 条 · (\d+) 张图", txt)
        stat = "%s 轮 · %s 条 · %s 张图" % mm.groups() if mm else ""
        dt = datetime.date.fromisoformat(date)
        rows.append('<div class="tw"><div class="when">%s<i>%s</i></div>'
                    '<div class="body"><a href="%s" style="font-weight:800;font-size:15px">'
                    '%s X 盘中简报</a><div class="note">%s</div></div></div>'
                    % (date[5:], WEEKDAYS[dt.weekday()], f.name, date, stat))
    page = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>X 盘中简报</title>
<style>
%s
%s
</style>
<div class="wrap">
<header><div class="eyebrow">xdesk</div><h1>X 盘中简报</h1>
<div class="note" style="margin-top:8px">一天一页，当天多轮扫描追加进同一页，最新一轮在最上面。</div>
</header>
%s
</div>
""" % (CSS_PATH.read_text(encoding="utf-8"), EXTRA_CSS,
       "".join(rows) or '<div class="miss">还没有任何一天的简报。</div>')
    (OUTDIR / "index.html").write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--no-media", action="store_true", help="不下载图片，直接引用 X 的 CDN")
    ap.add_argument("--allow-promo", action="store_true",
                    help="放行广告帖闸门（默认拦截，只有误判时才用）")
    ap.add_argument("--allow-roster-gap", action="store_true",
                    help="放行名单闸门（默认要求扫全 data/x_accounts.json）")
    a = ap.parse_args()
    out, nruns, nitems, nimg = build_day(a.date, a.no_media, a.allow_promo, a.allow_roster_gap)
    build_index()
    print("✅ %s" % out)
    print("   %d 轮 · %d 条 · %d 张图" % (nruns, nitems, nimg))


if __name__ == "__main__":
    main()
