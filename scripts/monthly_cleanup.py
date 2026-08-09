#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每月一次的清理 routine（2026-08-07 Vic：「每月做 routine 删一次，我电脑很旧」）。

清两类可再生的东西：
  ① Claude Code 会话记录 `~/.claude/projects/**/*.jsonl`——超过 KEEP_DAYS 天的
     ⚠️删掉就不能 `--resume` 那些会话了。已提炼进 CONTEXT.md 的结论不受影响，
     但**没提炼的原始讨论细节会永久消失**——所以默认只删满 30 天的。
  ② 项目 cache `data/cache/*.json`——超过 KEEP_DAYS 天的
     这些是 fetch_market_data / scan_setups 等脚本的输出，**随时可以重跑再生**，
     删掉零风险。唯一例外见 KEEP_PATTERNS。

**默认 dry-run，只报不删**。确认无误后加 --yes 才真删。

    python scripts/monthly_cleanup.py            # 看会删什么
    python scripts/monthly_cleanup.py --yes      # 真删
    python scripts/monthly_cleanup.py --days 21 --yes
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
SESSIONS = Path(os.path.expanduser("~")) / ".claude" / "projects"
CACHE = ROOT / "data" / "cache"

# cache 里不删的：x_scan 是子代理跑一次要几分钟+烧 token 的，比其他 cache 贵得多；
# weinstein 跑一次要几分钟。这两类留着，其余（market/setups/premarket/semis/earnings）随便删。
KEEP_PATTERNS = ("x_scan_", "weinstein_")


def collect(root: Path, pattern: str, cutoff: float, skip_prefixes=()):
    out = []
    if not root.exists():
        return out
    for f in root.rglob(pattern):
        if not f.is_file():
            continue
        if any(f.name.startswith(p) for p in skip_prefixes):
            continue
        if f.stat().st_mtime < cutoff:
            out.append(f)
    return sorted(out, key=lambda x: -x.stat().st_size)


def show(title, files, note=""):
    mb = sum(f.stat().st_size for f in files) / 1e6
    print("\n%s：%d 个，%.1f MB %s" % (title, len(files), mb, note))
    for f in files[:8]:
        print("   %6.2f MB  %s  %s" % (f.stat().st_size / 1e6,
                                       time.strftime("%Y-%m-%d", time.localtime(f.stat().st_mtime)),
                                       f.name[:44]))
    if len(files) > 8:
        print("   ... 另外 %d 个" % (len(files) - 8))
    return mb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="保留最近N天（默认30）")
    ap.add_argument("--yes", action="store_true", help="真的删除（默认只报不删）")
    args = ap.parse_args()
    cutoff = time.time() - args.days * 86400

    print("=" * 62)
    print("每月清理 · 保留最近 %d 天 · %s"
          % (args.days, "**执行删除**" if args.yes else "预演（不删，加 --yes 才删）"))
    print("=" * 62)

    sess = collect(SESSIONS, "*.jsonl", cutoff)
    cach = collect(CACHE, "*.json", cutoff, skip_prefixes=KEEP_PATTERNS)

    m1 = show("会话记录 ~/.claude/projects", sess, "⚠️删后无法 --resume")
    m2 = show("项目 cache data/cache", cach, "（可重跑再生，零风险）")

    print("\n" + "-" * 62)
    print("合计可释放 %.1f MB" % (m1 + m2))
    if not args.yes:
        print("\n预演结束，什么都没删。确认后跑：python scripts/monthly_cleanup.py --yes")
        return
    n = 0
    for f in sess + cach:
        try:
            f.unlink()
            n += 1
        except OSError as e:
            print("  跳过 %s：%s" % (f.name, e))
    print("\n已删除 %d 个文件，释放 %.1f MB" % (n, m1 + m2))


if __name__ == "__main__":
    main()
