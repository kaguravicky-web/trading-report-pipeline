# -*- coding: utf-8 -*-
"""13F / 13D / 13G 定向扫描（2026-08-17 建）。

🔴 **为什么是「定向」**：8/17 第一版从 EDGAR getcurrent feed 抓「最近 100 笔 13F-HR」，
   再用「Claude 认得出名字的机构」筛，报告里写了「唯一有分量的是 Anatole/NBIS」。
   Vic 一句「你没有查到 nvda 的 13F?」戳穿两个问题：
     ① 一个 13F 季有 6000+ 家申报，**100 笔 = 随机 1.6% 的时间切片**，抓到谁全看运气；
     ② 「认得出名字」是模型的先验，**英伟达自己就不在那份临时名单里**——
        而它本季新建仓 SpaceX $20.98B，占其 13F 组合 33.1%。
   更糟的是**失败是静默的**：报告照样写得出「今天没什么」，看不出是真没有还是没扫到。

🎯 改法：名单写在 `data/institutions.json`（谁在里面、为什么、为什么不要谁），
   按 CIK 走 data.sec.gov/submissions → 13F-HR → infoTable。
   名单稳定、可审计、能逐季对比。

用法：
    python scripts/scan_13f.py                 # 扫本季（默认 since = 本月 1 号）
    python scripts/scan_13f.py --since 2026-08-01
    python scripts/scan_13f.py --json          # 只吐 JSON，给 assemble 用
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Vic Trading Research kaguravicky@gmail.com"}

# 标的名 → ticker。**前缀精确匹配**，不是子串包含：
# 8/17 用子串匹配时 "OWENS CORNING NEW"（欧文斯科宁 OC）被当成了 CORNING(GLW)，
# 差点把 Lodge Hill 9% 的仓位写成「机构重仓你的 GLW」。
ISSUER_MAP = {
    "MARVELL TECHNOLOGY": "MRVL", "SERVICENOW": "NOW", "OKTA": "OKTA",
    "SOFI TECHNOLOGIES": "SOFI", "MICRON TECHNOLOGY": "MU", "CIRCLE INTERNET": "CRCL",
    "TERADYNE": "TER", "SENTINELONE": "S", "CORNING INC": "GLW", "NETFLIX": "NFLX",
    "ROCKET LAB": "RKLB", "PALO ALTO NETWORKS": "PANW", "ARISTA NETWORKS": "ANET",
    "CLOUDFLARE": "NET", "PALANTIR": "PLTR", "CROWDSTRIKE": "CRWD", "NEBIUS": "NBIS",
    "SNOWFLAKE": "SNOW", "BROADCOM": "AVGO", "SANDISK": "SNDK", "NVIDIA": "NVDA",
    "SPACE EXPLORATION": "SPCX", "COREWEAVE": "CRWV", "EVERSPIN": "MRAM",
    "FORTINET": "FTNT", "AXT INC": "AXTI", "AMPRIUS": "AMPX", "BLOOM ENERGY": "BE",
    "HEICO": "HEI", "ALKAMI": "ALKT", "ROBINHOOD": "HOOD", "INTEL CORP": "INTC",
}


def _get(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            time.sleep(1.2)
    raise RuntimeError("取数失败 %s（%s）" % (url, last))


def load_roster():
    p = ROOT / "data" / "institutions.json"
    if not p.exists():
        sys.exit("🔴 找不到 data/institutions.json——**名单是这个模块的前提**，不要临时拍脑袋补")
    return json.loads(p.read_text(encoding="utf-8"))["filers"]


def _infotable(cik, acc):
    a = acc.replace("-", "")
    idx = _get("https://www.sec.gov/Archives/edgar/data/%d/%s/%s-index.htm" % (int(cik), a, acc))
    for xu in re.findall(r'href="(/Archives/[^"]+\.xml)"', idx):
        x = _get("https://www.sec.gov" + xu)
        if "infoTable" in x:
            return x
        time.sleep(0.15)
    return None


def holdings(cik, acc):
    """→ {issuer: usd}。value 单位是**美元**（2023 年起，不再是千美元）。"""
    tbl = _infotable(cik, acc)
    if not tbl:
        return {}
    agg = {}
    for b in re.findall(r"<(?:\w+:)?infoTable>(.*?)</(?:\w+:)?infoTable>", tbl, re.S):
        iss = re.search(r"<(?:\w+:)?nameOfIssuer>([^<]+)<", b)
        val = re.search(r"<(?:\w+:)?value>([^<]+)<", b)
        if not iss:
            continue
        k = iss.group(1).strip().upper()
        agg[k] = agg.get(k, 0) + (int(float(val.group(1))) if val else 0)
    return agg


def scan(since):
    roster, out = load_roster(), []
    for name, cik in roster.items():
        try:
            j = json.loads(_get("https://data.sec.gov/submissions/CIK%s.json" % cik))
            r = j["filings"]["recent"]
            acc = filed = None
            for i, f in enumerate(r["form"]):
                if f == "13F-HR" and r["filingDate"][i] >= since:
                    acc, filed = r["accessionNumber"][i], r["filingDate"][i]
                    break
            if not acc:
                out.append({"filer": name, "status": "未申报"})
                continue
            agg = holdings(cik, acc)
            tot = sum(agg.values()) or 1
            hits = []
            for iss, v in agg.items():
                for k, tk in ISSUER_MAP.items():
                    if iss.startswith(k):
                        hits.append({"ticker": tk, "usd_m": round(v / 1e6, 1),
                                     "pct": round(v / tot * 100, 2)})
            hits.sort(key=lambda x: -x["pct"])
            out.append({"filer": name, "status": "ok", "filed_date": filed,
                        "n_holdings": len(agg), "aum_m": round(tot / 1e6),
                        "hits": hits})
            time.sleep(0.3)
        except Exception as e:
            out.append({"filer": name, "status": "错误：%s" % e})
    return out


def scan_13dg():
    """13D/13G 仍走 getcurrent——它是**事件流**不是季度快照，全量看就是对的。"""
    u = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC+13"
         "&company=&dateb=&owner=include&count=100&output=atom")
    return re.findall(r"<title>(SC 13[^<]+)</title>", _get(u))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=date.today().replace(day=1).isoformat())
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    res = scan(a.since)
    dg = scan_13dg()
    if a.json:
        print(json.dumps({"since": a.since, "filers": res, "sc13": dg},
                         ensure_ascii=False, indent=1))
        return
    for r in res:
        if r["status"] != "ok":
            print("%-22s %s" % (r["filer"], r["status"]))
            continue
        print("== %-20s %s  %d 只 / $%dM" % (r["filer"], r["filed_date"],
                                             r["n_holdings"], r["aum_m"]))
        for h in r["hits"]:
            print("     %-5s $%9.1fM  %5.2f%%" % (h["ticker"], h["usd_m"], h["pct"]))
    print("\n13D/13G（getcurrent，事件流）：%d 笔" % len(dg))
    for t in dg[:20]:
        print("   ", t)


if __name__ == "__main__":
    main()
