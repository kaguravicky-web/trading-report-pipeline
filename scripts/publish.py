#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 output/ 推到 GitHub Pages —— 2026-08-20 建。

Vic 2026-08-20：「每次更新 Push github 我手机上看」。

站点：https://kaguravicky-web.github.io/trading-reports/
仓库：kaguravicky-web/trading-reports（**公开仓库**，`output/` 目录本身就是个 git 库，
      跟 `D:\\交易为生` 那个主库是两个不同的 repo，别搞混）

跑之前会先重建索引（`build_index.py`），免得推上去的 index.html 还是旧的、
点进去全是 404。

**不会上传的**（`output/.gitignore`）：
  - `tradebook.html`——完整交易台账，公开仓库不放
  - `财报交易助手.html`、旧的期权流页
  - `xdesk/media/`——X 帖子里的图。页面用「本地优先、远端兜底」写法：本地打开走
    下载好的副本，Pages 上那个路径 404 后自动回落到 X 自己的 CDN。这样手机上照样看得到图，
    仓库不用每天多背 1.5MB，也不用把别人的图转存到公开站点。

用法：
    python scripts/publish.py                    # 自动生成提交信息
    python scripts/publish.py -m "8/20 盘前"
    python scripts/publish.py --dry              # 只看会推什么，不推
"""
import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
SITE = "https://kaguravicky-web.github.io/trading-reports/"


def run(args, **kw):
    return subprocess.run(args, cwd=str(OUT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def changed_files():
    r = run(["git", "status", "--porcelain"])
    out = []
    for line in r.stdout.splitlines():
        if len(line) > 3:
            out.append((line[:2].strip(), line[3:].strip()))
    return out


def auto_message(files):
    """按改了什么自动拼一句提交信息，别每次都是 'update'。"""
    kinds = []
    names = [f for _, f in files]
    for pat, label in ((r"^premarket/", "盘前"), (r"^postmarket/", "盘后"),
                       (r"^xdesk/", "X盘中"), (r"^weekly/", "周报"),
                       (r"^monthly/", "月报"), (r"^special/", "专题")):
        n = sum(1 for f in names if re.search(pat, f))
        if n:
            kinds.append("%s×%d" % (label, n) if n > 1 else label)
    dates = sorted({m.group(1) for f in names
                    for m in [re.search(r"(\d{4}-\d{2}-\d{2})", f)] if m})
    span = dates[-1] if len(dates) == 1 else (
        "%s~%s" % (dates[0], dates[-1]) if dates else datetime.date.today().isoformat())
    return "%s %s" % (span, " + ".join(kinds) if kinds else "更新")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-index", action="store_true", help="不重建 index.html")
    a = ap.parse_args()

    if not (OUT / ".git").exists():
        sys.exit("output/ 不是 git 库，先确认仓库配置。")

    if not a.no_index:
        r = subprocess.run([sys.executable, "-X", "utf8",
                            str(ROOT / "scripts" / "build_index.py")],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            sys.exit("build_index.py 失败：\n" + (r.stderr or r.stdout))
        print("索引已重建")

    files = changed_files()
    if not files:
        print("没有改动，不用推。")
        return

    print("\n会推这些（%d 个）：" % len(files))
    for st, f in files[:40]:
        print("  %-2s %s" % (st, f))
    if len(files) > 40:
        print("  …还有 %d 个" % (len(files) - 40))

    msg = a.message or auto_message(files)
    if a.dry:
        print("\n（dry）提交信息会是：%s" % msg)
        return

    for cmd in (["git", "add", "-A"],
                ["git", "commit", "-m", msg],
                ["git", "push", "origin", "main"]):
        r = run(cmd)
        if r.returncode:
            sys.exit("%s 失败：\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))

    print("\n✅ 已推送：%s" % msg)
    print("   %s" % SITE)
    print("   Pages 构建通常 1 分钟内生效")


if __name__ == "__main__":
    main()
