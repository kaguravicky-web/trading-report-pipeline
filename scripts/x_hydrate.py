#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 tweet URL 补全帖子内容（全文 + 图片 URL）—— 2026-08-20 建。

**为什么不在浏览器里抓图**：X 的媒体是懒加载的，帖子不进视口就不渲染 `<img>`；
而 MCP 标签页是后台态（`document.visibilityState === "hidden"`），IntersectionObserver
永远不触发，`article` 里除了头像一张图都没有——8/20 实测逐条 `scrollIntoView` 也拿不到。
在页面里 `fetch` 拿也不行，x.com 的 CSP 把跨域请求挡了。

**改成 Python 侧走 syndication 端点**（X 给第三方嵌入推文用的公开接口，无需登录）：

    https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=<算出来的>

一次调用同时解决三件事：
  1. **图片 URL**（`photos[].url` / `mediaDetails[]`）——本来就是这次要的东西；
  2. **全文**——绕开 X 的「Show more」截断，比 DOM 里的 innerText 还全；
  3. **精确时间**（`created_at`）。

于是浏览器那边的活变轻了：**只要滚出 tweet 链接和时间戳**，正文和图都交给这里补。
子代理不用再为了拿全文反复 `read_page`，token 成本直接掉一大截。

结果缓存在 `data/cache/x_tweets.json`，同一条推只取一次。

用法：
    python scripts/x_hydrate.py https://x.com/xxx/status/123      # 单条，打印
    python scripts/x_hydrate.py --file data/cache/x_intraday_20260820.json   # 批量补全并回写
"""
import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "data" / "cache" / "x_tweets.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def tweet_id(url_or_id):
    s = str(url_or_id)
    m = re.search(r"/status/(\d+)", s)
    if m:
        return m.group(1)
    return s if s.isdigit() else None


def _b36(x):
    """浮点数转 base36（JS 的 Number.prototype.toString(36) 等价实现）。"""
    ip = int(x)
    fp = x - ip
    s = ""
    if ip == 0:
        s = "0"
    while ip:
        s = DIGITS[ip % 36] + s
        ip //= 36
    frac = ""
    for _ in range(20):
        fp *= 36
        d = int(fp)
        frac += DIGITS[d]
        fp -= d
    return s + "." + frac


def _token(tid):
    """X 嵌入脚本里的 token 算法：((id/1e15)*PI).toString(36) 去掉 0 和小数点。"""
    return _b36((int(tid) / 1e15) * math.pi).replace("0", "").replace(".", "")


def _load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(c):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_tweet(url_or_id, cache=None, timeout=20, retries=2):
    """返回 {text, photos[], created_at, handle, likes, quoted} 或 None。

    失败（推被删/受保护/限流）返回 None——**不编内容**，渲染时该条就只有扫描时
    记下的那句摘要，页面上不会假装有图。
    """
    tid = tweet_id(url_or_id)
    if not tid:
        return None
    if cache is not None and tid in cache:
        return cache[tid]

    url = ("https://cdn.syndication.twimg.com/tweet-result"
           "?id=%s&token=%s&lang=en" % (tid, _token(tid)))
    j = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < retries:      # 限流，退避重试
                time.sleep(2 + 3 * i)
                continue
            print("  [hydrate] %s HTTP %s" % (tid, e.code), file=sys.stderr)
            return None
        except Exception as e:
            if i < retries:
                time.sleep(1.5)
                continue
            print("  [hydrate] %s %s" % (tid, e), file=sys.stderr)
            return None
    if not j or j.get("__typename") == "TweetTombstone":
        return None

    photos = [p.get("url") for p in (j.get("photos") or []) if p.get("url")]
    for m in (j.get("mediaDetails") or []):
        u = m.get("media_url_https")
        if u and u not in photos:
            photos.append(u)
    vid = (j.get("video") or {}).get("poster")
    if vid and vid not in photos:
        photos.append(vid)                          # 视频帖用封面帧代替

    q = j.get("quoted_tweet") or {}
    out = {
        "id": tid,
        "text": (j.get("text") or "").strip(),
        "photos": photos,
        "created_at": j.get("created_at"),
        "handle": "@" + ((j.get("user") or {}).get("screen_name") or ""),
        "likes": j.get("favorite_count"),
        "quoted": ("@%s：%s" % ((q.get("user") or {}).get("screen_name", ""),
                                (q.get("text") or "")[:280])) if q else "",
        "is_video": bool(j.get("video")),
    }
    if cache is not None:
        cache[tid] = out
    return out


def hydrate_file(path, sleep=0.35):
    """批量补全一个 x_intraday_*.json：给每个 item 填 media / full_text / quoted。"""
    p = Path(path)
    d = json.loads(p.read_text(encoding="utf-8"))
    cache = _load_cache()
    n_ok = n_img = n_fail = 0
    for run in d.get("runs") or []:
        for it in run.get("items") or []:
            if not it.get("url"):
                continue
            t = fetch_tweet(it["url"], cache)
            if t is None:
                n_fail += 1
                continue
            n_ok += 1
            if t["photos"]:
                it["media"] = t["photos"]
                n_img += len(t["photos"])
            if t["text"] and not it.get("full_text"):
                it["full_text"] = t["text"]
            if t["quoted"] and not it.get("quoted"):
                it["quoted"] = t["quoted"]
            if t["created_at"] and not it.get("utc"):
                it["utc"] = t["created_at"]
            time.sleep(sleep)                       # 别把公开端点打太急
    _save_cache(cache)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print("补全 %d 条 · %d 张图 · %d 条取不到" % (n_ok, n_img, n_fail))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--file")
    a = ap.parse_args()
    if a.file:
        hydrate_file(a.file)
    elif a.url:
        print(json.dumps(fetch_tweet(a.url, _load_cache()), ensure_ascii=False, indent=1))
    else:
        ap.error("给个 tweet URL 或 --file")


if __name__ == "__main__":
    main()
