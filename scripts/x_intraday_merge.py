#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已经跑过的盘前/盘后 X 扫描导进 xdesk 当天页 —— 2026-08-20 建。

Vic 2026-08-20：「如果我跑过盘前盘后，时间上有重复的，你就不用重复跑，看时间戳，
直接拿了加入这个页面」。

所以喊「x盘中」时的第一件事**不是**开浏览器，是先问「这段时间是不是已经扫过了」：

    python scripts/x_intraday_merge.py --status     # 今天覆盖到哪了、缺口是多少
    python scripts/x_intraday_merge.py              # 把盘前扫描导进 xdesk 页

`--status` 把三个来源的时间戳并起来算覆盖：
  1. `data/cache/x_scan_YYYYMMDD.json`（盘前扫描，含它里面的 `delta_scan` 增量段）
  2. `data/cache/x_intraday_YYYYMMDD.json` 里已有的 `runs[]`
  3. 盘后如果也留了扫描结果，同样按 1 处理
然后告诉你**只需要扫「最后覆盖点 → 现在」这一段**，前面的直接导，不重复开浏览器。

🔴 **导进来的条目没有图**：盘前扫描只记 `handle` / 时间 / 文字摘要，**没有 tweet 链接**，
没链接就没法用 syndication 补图。CONTEXT.md 已经把「盘前扫描每条也要记 `url`」写进规程，
从下一次盘前开始导进来的就能带图了。老数据补不回来，不硬凑。

**时间格式两种都认**：2026-08-20 起盘前扫描给的是精确 UTC（`2026-08-19T20:28:59Z`），
更早的是手写的 "8/19 12:07 SGT" / "8/18"。只有日期没有时分的标 `time_approx`，
**不参与覆盖窗口计算**——否则会把没扫到的时段当成扫过了。

**当天盘前扫描被重跑/补充过**：加 `--redo`，先清掉上次导入的段再导一遍，
xdesk 自己扫的轮次不动。
"""
import argparse
import datetime
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SGT = datetime.timezone(datetime.timedelta(hours=8))
UTC = datetime.timezone.utc

# 盘前扫描的分组 -> xdesk 的 kind / 是否降权。
# 2026-08-20 那次盘前扫描新增了 trump_policy 和 ep_candidates 两组，字段名跟前面几组不一样
# （用 utc/source 而不是 time/handle），normalize() 统一吸收，别再给每组写一份解析。
#
# 🔴 **顺序＝特异性，从窄到宽，不要按字母排**：同一条推会同时出现在两组里
# （8/20 实测：@jimcramer 那两条在 `stocks` 和 `cramer` 里各有一份）。去重是先到先得，
# 所以窄的组必须先处理——否则 Cramer 的推被当成普通个股条目留下，「反指」降权标注就丢了，
# 而那是框架规则不是装饰。
GROUPS = {
    "cramer":       ("cramer", True),
    "congress":     ("congress", False),
    "thirteen_f_x": ("13f", False),
    "ep_candidates": ("ep", False),
    "stocks":       ("stock", False),
    "trump_policy": ("macro", False),
    "macro":        ("macro", False),
}


def parse_scan_time(s, date):
    """把盘前扫描的时间字段解析成 UTC ISO 串，返回 (iso, approx)。

    两种格式都要认：
      - **新格式（2026-08-20 起）**：`2026-08-19T20:28:59Z`，已经是精确 UTC，直接用。
      - **老格式**："8/19 12:07 SGT" / "8/18" / "8/17 17:38 SGT+8换算约01:38 8/18"，
        只认开头的 M/D 和紧跟的 HH:MM，按 SGT 换算。

    没有时分的（只有日期）标 approx=True——**近似时间不能用来算覆盖窗口的右端**，
    否则会把「其实没扫到」的时段当成已覆盖，下一轮就漏了。
    """
    s = str(s or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", s)
    if m:
        return (s if s.endswith("Z") else s + "Z", False)
    m = re.match(r"(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?", s)
    if not m:
        return (None, True)
    mo, dy = int(m.group(1)), int(m.group(2))
    if m.group(3) is None:
        dt = datetime.datetime(date.year, mo, dy, 0, 0, tzinfo=SGT)
        return (dt.astimezone(UTC).isoformat().replace("+00:00", "Z"), True)
    dt = datetime.datetime(date.year, mo, dy, int(m.group(3)), int(m.group(4)), tzinfo=SGT)
    return (dt.astimezone(UTC).isoformat().replace("+00:00", "Z"), False)


def parse_delta_time(s, date):
    """delta_scan 的 `utc` 字段是 "11:29" 或 "11:32-11:33" 这种纯 UTC 时分。"""
    m = re.match(r"(\d{1,2}):(\d{2})", str(s or ""))
    if not m:
        return (None, True)
    dt = datetime.datetime(date.year, date.month, date.day,
                           int(m.group(1)), int(m.group(2)), tzinfo=UTC)
    return (dt.isoformat().replace("+00:00", "Z"), False)


def dedup_keys(it):
    """一条 item 的所有认重钥匙，任一撞上就算重复。

    盘前扫描的条目**没有 tweet 链接**，而 xdesk 自己扫的有——只按 URL 去重的话，
    同一条推会以两个来源各出现一次（8/20 首次导入时 MRNA / 伊朗那几条就是这样）。
    所以再加一把「账号 + 精确到分钟的时间戳」的钥匙：新格式扫描的时间戳是精确 UTC，
    这个匹配是可靠的。近似时间（只有日期）不参与，否则同账号当天所有条目会互相误杀。
    """
    keys = []
    if it.get("url"):
        keys.append(("u", it["url"]))
    handle = (it.get("handle") or "").strip().lstrip("@").lower()
    utc = str(it.get("utc") or "")
    if handle and utc and not it.get("time_approx"):
        keys.append(("hm", handle, utc[:16]))
    txt = (it.get("summary") or it.get("note") or "")[:40]
    keys.append(("t", handle, utc[:16], txt))
    return keys


def normalize(e, group, kind, demoted, date):
    """把盘前扫描各组字段名不一的条目压成 xdesk 的 item。

    字段别名：时间 `time` / `utc`，账号 `handle` / `source`，正文 `summary` / `note`，
    代码 `ticker` / `tickers`。`ep_candidates` 那组本身不是一条推、没有时间戳，
    是扫描时归纳出来的候选，所以正文由 catalyst + move + volume 拼起来，时间记为近似。
    """
    utc, approx = parse_scan_time(e.get("time") or e.get("utc"), date)
    handle = e.get("handle") or e.get("source") or ""
    if group == "cramer" and not handle:
        handle = "@jimcramer"

    if group == "ep_candidates":
        # 这组的 source 是一长串出处（"@A/@B/@C 2026-08-19；评级来自二手转述"），
        # 归到正文末尾当出处说明，**不要塞进时间字段**——时间列只有 60px 宽，
        # 塞进去会截成 "@Watcher原文记的时" 这种没法看的东西。
        parts = [("催化剂：" + e["catalyst"]) if e.get("catalyst") else "",
                 ("走势：" + e["move"]) if e.get("move") else "",
                 ("量：" + e["volume"]) if e.get("volume") else "",
                 ("出处：" + e["source"]) if e.get("source") else ""]
        summary = "　".join(p for p in parts if p)
        handle = "盘前扫描归纳"
        approx = True
        raw_time = "归纳"
    else:
        summary = e.get("summary") or e.get("note") or ""
        raw_time = e.get("time") or e.get("utc")

    return {
        "handle": handle,
        "utc": utc,
        "time": raw_time,
        "time_approx": approx,
        "kind": kind,
        "ticker": e.get("ticker") or e.get("tickers"),
        "summary": summary,
        "url": e.get("url"),
        "media": e.get("media") or [],
        "demoted": demoted or None,
    }


def from_scan(path, date):
    """`x_scan_*.json` -> (主扫描 run, delta_scan run 或 None)。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    items = []
    for group, (kind, demoted) in GROUPS.items():
        for e in (d.get(group) or []):
            items.append(normalize(e, group, kind, demoted, date))
    items.sort(key=lambda x: x.get("utc") or "")
    main = {
        "run_id": "盘前",
        "label": "盘前扫描（导入，未重复跑）",
        "run_at": d.get("generated_at") or ("%sT12:00+08:00" % date.isoformat()),
        "window": "盘前扫描的近一周窗口",
        "source": "x_scan",
        "accounts_checked": d.get("accounts_scanned") or [],
        "accounts_no_new": d.get("accounts_no_content") or [],
        "items": items,
        "takeaway": None,
        "notes": ("从 `%s` 导入，没有重新开浏览器。这些条目是老格式（无 tweet 链接），"
                  "所以没有图。" % Path(path).name),
    }

    delta = d.get("delta_scan")
    drun = None
    if delta and (delta.get("items") or []):
        ditems = []
        for e in delta["items"]:
            utc, approx = parse_delta_time(e.get("utc"), date)
            ditems.append({
                "handle": e.get("handle") or "",
                "utc": utc,
                "time": e.get("utc"),
                "time_approx": approx,
                "kind": "stock" if e.get("ticker") not in (None, "—", "") else "macro",
                "ticker": e.get("ticker"),
                "summary": e.get("note") or "",
                "media": [],
                "demoted": True if "降权" in (e.get("handle") or "")
                           or "反指" in (e.get("handle") or "") else None,
            })
        ditems.sort(key=lambda x: x.get("utc") or "")
        drun = {
            "run_id": "盘前增量",
            "label": "盘前增量段（导入）",
            "run_at": delta.get("run_at") or main["run_at"],
            "window": delta.get("window") or "",
            "source": "x_scan.delta_scan",
            "accounts_checked": delta.get("accounts_checked") or [],
            "accounts_no_new": delta.get("accounts_no_new") or [],
            "items": ditems,
            "notes": "从盘前扫描的 delta_scan 段导入。",
        }
    return main, drun


def load_intraday(date):
    p = CACHE / ("x_intraday_%s.json" % date.strftime("%Y%m%d"))
    if p.exists():
        return p, json.loads(p.read_text(encoding="utf-8"))
    return p, {"date": date.isoformat(), "runs": []}


def coverage(date, d=None, look_back_days=3):
    """算已经覆盖到哪个 UTC 时刻。近似时间戳（只有日期没有时分）不算数。

    🔴 **跨天必须往回看**（2026-08-21 修）：只看当天文件的话，早上第一次跑
    `--status` 会说「今天还没有任何覆盖，回溯 2 小时」——而实际上昨天傍晚已经
    扫到了昨天 13:20 UTC，中间隔着**整整一个美股交易日**。按 2 小时窗口扫等于
    把昨晚的盘中全漏掉，而且漏得静悄悄。所以当天没有覆盖时，往前找最近几天的
    `x_intraday_*.json`，用它们的最后一条当起点。

    传 d 就用传进来的（`--status` 要算「导入之后」的覆盖，那份还没落盘）。
    """
    if d is None:
        _, d = load_intraday(date)
    latest, srcs = None, []
    for r in d.get("runs") or []:
        best = max((it.get("utc") or "") for it in (r.get("items") or [])
                   if it.get("utc") and not it.get("time_approx")) if r.get("items") else ""
        if best:
            srcs.append((r.get("label") or ("第 %s 轮" % r.get("run_id")), best))
            latest = max(latest or "", best)

    if latest is None:
        for back in range(1, look_back_days + 1):
            prev = date - datetime.timedelta(days=back)
            _, pd_ = load_intraday(prev)
            for r in pd_.get("runs") or []:
                best = max((it.get("utc") or "") for it in (r.get("items") or [])
                           if it.get("utc") and not it.get("time_approx")) \
                    if r.get("items") else ""
                if best:
                    latest = max(latest or "", best)
            if latest:
                srcs.append(("%s 最后扫到" % prev.isoformat(), latest))
                break
    return latest, srcs


def merge(date, dry=False, redo=False):
    scan = CACHE / ("x_scan_%s.json" % date.strftime("%Y%m%d"))
    p, d = load_intraday(date)
    if not scan.exists():
        print("今天没有 %s，没什么可导的。" % scan.name)
        return d

    if redo:
        # 盘前扫描当天被重跑/补充过就用这个：先扔掉上次导入的段再导一遍。
        # 只删导入来源的段，xdesk 自己扫的轮次不动。
        before = len(d.get("runs") or [])
        d["runs"] = [r for r in (d.get("runs") or [])
                     if not str(r.get("source") or "").startswith("x_scan")]
        print("重导：清掉 %d 段旧的导入" % (before - len(d["runs"])))

    have = {r.get("source") for r in (d.get("runs") or [])}
    seen = set()
    for r in (d.get("runs") or []):
        for it in (r.get("items") or []):
            seen.update(dedup_keys(it))

    added_runs, added_items, skipped = 0, 0, 0
    for run in from_scan(scan, date):
        if run is None or run["source"] in have:
            continue
        keep = []
        for it in run["items"]:
            ks = dedup_keys(it)
            if any(k in seen for k in ks):
                skipped += 1
                continue
            seen.update(ks)
            keep.append(it)
        if not keep:
            continue
        run["items"] = keep
        d.setdefault("runs", []).append(run)
        added_runs += 1
        added_items += len(keep)

    if dry:
        print("（dry-run）会导入 %d 段 · %d 条（跳过 %d 条已有的）"
              % (added_runs, added_items, skipped))
        return d
    d["date"] = date.isoformat()
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print("导入 %d 段 · %d 条 -> %s（跳过 %d 条重复）"
          % (added_runs, added_items, p.name, skipped))
    return d


def status(date):
    d = merge(date, dry=True)
    latest, srcs = coverage(date, d)
    print("\n导入后覆盖到：")
    for name, t in sorted(srcs, key=lambda x: x[1]):
        print("  %-24s 到 %s UTC" % (name, t[11:16]))
    if not srcs:
        print("  （空）")
    now = datetime.datetime.now(UTC)
    if latest:
        gap = now - datetime.datetime.fromisoformat(latest.replace("Z", "+00:00"))
        h, m = divmod(int(gap.total_seconds()) // 60, 60)
        # 跨天时只印时分会看不懂（「13:20 → 04:08」像在倒着走），带上日期
        nows = now.strftime("%Y-%m-%dT%H:%M")
        same = latest[:10] == nows[:10]
        f = (lambda t: t[11:16]) if same else (lambda t: t[5:10] + " " + t[11:16])
        print("\n🔴 只需要扫：%s → %s UTC（缺口 %d 小时 %d 分）"
              % (f(latest), f(nows), h, m))
    else:
        print("\n🔴 今天还没有任何覆盖，按默认回溯 2 小时扫。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--status", action="store_true", help="只看覆盖情况和缺口，不写盘")
    ap.add_argument("--redo", action="store_true",
                    help="先清掉之前导入的段再重导（盘前扫描当天被重跑过时用）")
    a = ap.parse_args()
    date = datetime.date.fromisoformat(a.date)
    status(date) if a.status else merge(date, redo=a.redo)


if __name__ == "__main__":
    main()
