# -*- coding: utf-8 -*-
"""对全部历史报告跑一遍 QA，统计每条检查真正抓到过几次。
   目的：找出「从没失败过」的检查——它们要么是我从不犯的错，要么已被渲染层收口，
   留着只会让 QA 看起来很满、实际不抓东西。"""
import sys, io, re
from pathlib import Path
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(r"D:\交易为生")
sys.path.insert(0, str(ROOT / "scripts"))
import json
import qa_report as Q

htmls = sorted(list((ROOT / "output").rglob("*-premarket.html"))
               + list((ROOT / "output").rglob("*-postmarket.html"))
               + list((ROOT / "output").rglob("*-weekly.html"))
               + list((ROOT / "output").rglob("*-monthly.html")))
hits = defaultdict(int)
runs = defaultdict(int)
first_seen = {}
for h in htmls:
    stem = h.stem
    jp = ROOT / "data" / "daily" / (stem + ".json")
    if not jp.exists():
        for alt in (ROOT / "data" / "daily").glob(stem.split("-")[0] + "*"):
            pass
    html = h.read_text(encoding="utf-8")
    data = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else None
    for name, fn, fatal in Q.CHECKS:
        runs[name] += 1
        try:
            r = fn(html, data)
        except Exception as e:
            r = None
        if r:
            hits[name] += 1
            first_seen.setdefault(name, stem)

print("报告数：%d\n" % len(htmls))
print("%-6s %-6s %s" % ("抓到", "跑过", "检查名（首次抓到）"))
print("-" * 100)
for name, fn, fatal in sorted(Q.CHECKS, key=lambda x: hits[x[0]]):
    short = re.sub(r"（.*", "", name)[:38]
    mark = "  " if hits[name] else "🔴"
    print("%s %-4d %-6d %-40s %s" % (mark, hits[name], runs[name], short,
                                     first_seen.get(name, "—— 从没抓到过")))
