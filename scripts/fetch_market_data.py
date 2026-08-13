#!/usr/bin/env python3
"""每日行情数据自动计算脚本（2026-07-07新增，Vic确认的改进#2）。

用LongPort官方SDK批量拉取全部跟踪标的的日K线，机器算数字，Claude只负责叙事判断——
之前每份报告靠手工拼JSON+临时心算，出过好几次错（giveback表漏算、ASX/STM判断先错后改）。

一次运行输出 data/cache/market_YYYYMMDD.json，包含：
  - 每只标的：T-1收盘/T-1%、5日%、21日%、距20/50/200MA%、RSI14、收盘位置%（当日区间）、10日结构
  - 单边板块扫描排行榜（58只板块ETF按结构标准打分）
  - SPY/QQQ/IWM闸门线参考值（20MA、±1SD，周一重算用）
  - 命中率滚动统计（扫data/daily/*-postmarket.json）
  - X trader台账定价（data/x_watch.json里每条提及的最新表现）
  - 信号灯历史台账维护（append当天信号+回填前日的次日结果）

用法：
    python scripts/fetch_market_data.py            # 全量
    python scripts/fetch_market_data.py --quick    # 只跑指数+ML+篮子（跳过58只板块全量）

凭证走环境变量 LONGPORT_APP_KEY/SECRET/ACCESS_TOKEN（见CONTEXT.md「历史K线正式方案」）。
"""
import glob
import json
import math
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
DAILY_DIR = ROOT / "data" / "daily"
X_WATCH_PATH = ROOT / "data" / "x_watch.json"
SIGNAL_HISTORY_PATH = ROOT / "data" / "signal_history.json"

# ---------------- 标的清单（与CONTEXT.md各章节保持一致） ----------------
INDICES = ["SPY", "QQQ", "QQQE", "RSP", "DIA", "IWM", "VOO", "SMH"]
XL_SECTORS = ["XLK", "XLC", "XLY", "XLI", "XLF", "XLB", "XLE", "XLV", "XLP", "XLU", "XLRE"]
# 2026-07-07去重（Vic：同类主题只留日均量大的）：删XHS/IBB/UFO/ITB/QPUX/BOTZ，
# 分别由IAK/XBI/NASA/XHB/QTUM/AIQ覆盖
# XSW 2026-07-15加回（当时因流动性删掉由IGV覆盖，Vic纠正：XSW成分和IGV很不一样，要单独跟踪）
GROUP2 = ["SMH", "DRAM", "KOID", "AIQ", "CIBR", "IGV", "XSW", "MAGS", "ARKK", "QTUM", "EUV"]  # EUV: 2026-07-09 Vic新增
GROUP3 = ["NASA", "ITA", "AIRR", "XOP", "OIH", "TAN", "LIT", "COPX", "REMX", "SLV", "GLD",
          "URA", "IBIT", "WGMI", "ETHB", "FXI", "KWEB", "ASHR", "EWY",
          "XBI", "IHI", "PPH", "XHB", "PAVE", "KRE", "IAK", "JETS",
          # UUP 2026-07-27加入（Vic："我有做这个盘前辅助，你可以直接这里抓呀"）——
          # 他的宏观Sheet只给美元的**点位**(28.58)不给方向，而报告里要判断的是"美元走强还是走弱"。
          # 把UUP纳入SDK universe后就有T-1%/5日/MA/ATR全套，DXY这一行不用再依赖
          # investing.com（长期被Cloudflare拦），也不用再写"抓取失败"。
          "UUP"]
# ML Market Leader 名单。2026-08-05 Vic 加 ANET；2026-08-10 Vic 加 NET 和 PLTR
# ——三只正好卡在两条主线的三个层：ANET=AI网络层硬件 / NET=网安+AI骨干 / PLTR=AI应用软件。
# 🔴 这份名单的用途是**判断主线还在不在**，不是候选池；要买走 A/B/C 的止损距离门槛。
ML_LEADERS = ["ANET", "NET", "PLTR",
              "MRVL", "NBIS", "SNDK", "NOK", "MU", "CRDO", "STM", "BB", "GLW",
              "INTC", "DELL", "PWR", "FIX", "ASX"]
DEFENSIVE = ["PM", "KO", "PG", "TLT", "XLU", "XLP"]
LAODENG = ["BRK.B", "SCHD", "WMT", "WM", "MCD", "KO", "COR"]  # BRK.B单独试，MCP工具查不了但SDK可能行

# 光通信/AI 网络层全链（2026-08-10 Vic：「加进扫描池」）。
# 名单来自 sintszkay《光通信深度专题》v1.1（2026-08-10）盘点的 12 家，按它的质量排名注明：
#   AVGO 1(4.80) / ANET 2(4.38) / CRDO 3(4.25) / GLW 4(4.13) / MTSI 5(4.10) / FN 6(4.03)
#   ... COHR 10(3.50) / AAOI 11(2.83) / POET 12(1.93)
# 加它的理由是**排名前列的 CRDO / MTSI / FN 此前都不在候选池里**，而排名倒数的 AAOI 在持仓里。
# 🔴排名是「好公司」维度，不是「好价格」——专题自己说 12 家里 11 家估值偏热或极热。
OPTICAL_CHAIN = ["AVGO", "ANET", "CRDO", "GLW", "MTSI", "FN", "LITE", "MRVL",
                 "CIEN", "COHR", "AAOI", "POET"]

SECTOR_SCAN = list(dict.fromkeys(XL_SECTORS + GROUP2 + GROUP3 + OPTICAL_CHAIN))  # 单边扫描范围
BARS_NEEDED = 260  # 2026-07-15从220加到260：52周高点需要252根（200MA只要200根）

def position_tickers():
    """持仓票永远要在监控范围内，哪怕不在任何预设清单里。
    2026-07-16起改读data/tradebook.json（Vic："以后持仓，只扫描我的tradebook"）——
    data/positions.json不再维护，继续读它会让新仓漏出监控范围（价格显示为"-"）。"""
    tb = load_json(ROOT / "data" / "tradebook.json", {"trades": []})
    return [t["ticker"] for t in tb.get("trades", []) if t.get("status") == "open" and t.get("ticker")]


def universe(quick: bool):
    if quick:
        tickers = INDICES + ML_LEADERS + DEFENSIVE + LAODENG + OPTICAL_CHAIN
    else:
        tickers = INDICES + SECTOR_SCAN + ML_LEADERS + DEFENSIVE + LAODENG
    return list(dict.fromkeys(tickers + position_tickers()))


# ---------------- 指标计算（纯函数，只吃closes/highs/lows数组） ----------------
def sma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def stdev(vals, n):
    if len(vals) < n:
        return None
    window = vals[-n:]
    m = sum(window) / n
    return math.sqrt(sum((x - m) ** 2 for x in window) / n)


def atr14(bars):
    """Wilder ATR(14)。TR = max(高-低, |高-昨收|, |低-昨收|)。"""
    n = 14
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def ema(vals, n):
    if len(vals) < n:
        return None
    k = 2 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def rsi14(closes):
    n = 14
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def pct(a, b):
    """a相对b的百分比变化"""
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100


def weinstein_stage(close, ma150, slope_pct):
    """Weinstein四阶段（2026-07-27新增）。用30周均线(≈150交易日)与其10日斜率判定：
      Stage 2 上升 = 价在均线上 且 均线上行(斜率>+0.5%)
      Stage 4 下降 = 价在均线下 且 均线下行(斜率<-0.5%)
      Stage 1 筑底 = 价在均线下/附近 且 均线走平
      Stage 3 派发 = 价在均线上 但 均线走平或转下
    斜率带±0.5%的死区，避免均线微幅波动来回翻档。"""
    if close is None or ma150 is None or slope_pct is None:
        return None
    above = close >= ma150
    if slope_pct > 0.5:
        return 2 if above else 1
    if slope_pct < -0.5:
        return 3 if above else 4
    return 3 if above else 1


def analyze(bars):
    """bars: [{date, o, h, l, c}]，按时间升序。返回单标的全部指标。"""
    closes = [b["c"] for b in bars]
    last = bars[-1]
    prev_c = closes[-2] if len(closes) >= 2 else None
    ma20, ma50, ma200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    ma20_prev5 = sma(closes[:-5], 20) if len(closes) >= 25 else None
    # Weinstein 30周均线（≈150交易日）+ 斜率，用来判四阶段（2026-07-27新增，Vic要求单边榜加Weinstein筛选）
    ma150 = sma(closes, 150)
    ma150_prev10 = sma(closes[:-10], 150) if len(closes) >= 160 else None
    ma150_slope = (pct(ma150, ma150_prev10) if (ma150 and ma150_prev10) else None)
    atr = atr14(bars)
    ema9 = ema(closes[-40:], 9) if len(closes) >= 9 else None
    # 2026-07-23加ema20（Vic："距9EMA改成距离20ema/50ma先"）——轮动市里9EMA太贴、噪音大，
    # 回踩买点改用20EMA/50MA这两条更结构性的线做判据
    ema20 = ema(closes[-80:], 20) if len(closes) >= 20 else None

    # Setup筛选指标：tight consolidation（Setup B）与回踩9EMA距离（Setup A）
    # tight参数（见CONTEXT.md「选股规则」）：5日区间振幅<8%（框架原定）；辅以ATR归一化——5日区间<2.0×ATR14
    # （固定8%对低波动大盘股和高Beta小票不公平，ATR归一化让"tight"以该股自己的波动为尺）
    range5_pct = range5_atr = hi5 = lo5 = None
    if len(bars) >= 5:
        hi5 = max(b["h"] for b in bars[-5:])
        lo5 = min(b["l"] for b in bars[-5:])
        range5_pct = round((hi5 - lo5) / last["c"] * 100, 2)
        if atr:
            range5_atr = round((hi5 - lo5) / atr, 2)

    # 成交量基准：20日均量 + 当日量比（放量/缩量判断的尺）
    vol20 = sum(b["v"] for b in bars[-21:-1]) / 20 if len(bars) >= 21 else None
    vol_ratio = round(last["v"] / vol20, 2) if vol20 else None

    # Setup C · undercut and rally 机器初筛（参数见CONTEXT.md「选股规则」）：
    # 支撑 = 前15日最低点（不含最近3根）；最近3根里有K线的低点跌破支撑（假跌破深度≤5%，太深=真破位不是假摔）
    # 且当前收盘已收回支撑上方 → 候选。真正的rally确认（放量阳线）留给人眼/次日验证。
    undercut_rally = None
    if len(bars) >= 20:
        support = min(b["l"] for b in bars[-18:-3])
        recent = bars[-3:]
        under = [b for b in recent if b["l"] < support]
        if under and last["c"] > support:
            depth = (support - min(b["l"] for b in under)) / support * 100
            if depth <= 5.0:
                undercut_rally = {"support": round(support, 2), "undercut_depth_pct": round(depth, 2)}

    # Setup D · 放量突破→缩量回踩 机器初筛（参数见CONTEXT.md「选股规则」）：
    # 突破 = 最近6日内某天收盘站上此前20日高点且量≥1.5×20日均量；
    # 回踩 = 突破日之后每天量≤0.7×突破日量、当前价仍守在突破点上方（允许-1%以内的假破）
    breakout_pullback = None
    if len(bars) >= 30 and vol20:
        pivot = max(b["h"] for b in bars[-26:-6])
        bo_idx = None
        for i in range(len(bars) - 6, len(bars)):
            if bars[i]["c"] > pivot and bars[i]["v"] >= 1.5 * vol20:
                bo_idx = i
                break
        if bo_idx is not None and bo_idx < len(bars) - 1:
            after = bars[bo_idx + 1:]
            quiet = all(b["v"] <= 0.7 * bars[bo_idx]["v"] for b in after)
            holding = last["c"] >= pivot * 0.99
            pulled_back = last["c"] < bars[bo_idx]["c"]
            if quiet and holding and pulled_back:
                breakout_pullback = {"pivot": round(pivot, 2), "breakout_date": bars[bo_idx]["date"],
                                     "breakout_vol_ratio": round(bars[bo_idx]["v"] / vol20, 2)}

    # Setup E · shakeout + momentum burst 机器初筛（2026-07-15新增，Vic老师的PLTR案例，参数见CONTEXT.md「选股规则」）：
    # shakeout = 深度洗盘：收盘跌破前期基座低点（40根历史窗口的最低low）、在下方停留≥2根
    #   （区别于Setup C的3根内快速收回）、假破深度≤20%（更深=真破位），随后收盘收回支撑上方；
    # momentum burst = 收回后出现动量爆发bar：单日涨幅≥4%（Stockbee口径）或≥1.5×ATR%，
    #   且放量≥1.2×20日均量、当日收盘位置≥60。burst未出现时输出burst=None（E-watch状态，等开盘第一根动量bar）
    shakeout_burst = None
    if len(bars) >= 55 and vol20:
        base_support = min(b["l"] for b in bars[-55:-15])
        recent15 = bars[-15:]
        below_idx = [i for i, b in enumerate(recent15) if b["c"] < base_support]
        if len(below_idx) >= 2 and last["c"] > base_support:
            depth = (base_support - min(b["l"] for b in recent15)) / base_support * 100
            if depth <= 20.0:
                burst = None
                for i in range(max(below_idx) + 1, len(recent15)):
                    b = recent15[i]
                    pc = recent15[i - 1]["c"]
                    gain = pct(b["c"], pc)
                    brng = b["h"] - b["l"]
                    bpos = (b["c"] - b["l"]) / brng * 100 if brng > 0 else 0
                    atr_pct_bar = atr / pc * 100 if atr else None
                    big = gain >= 4.0 or (atr_pct_bar and gain >= 1.5 * atr_pct_bar)
                    if big and b["v"] >= 1.2 * vol20 and bpos >= 60:
                        burst = {"date": b["date"], "gain_pct": round(gain, 2),
                                 "vol_ratio": round(b["v"] / vol20, 2), "range_pos": round(bpos)}
                        break
                shakeout_burst = {"support": round(base_support, 2), "depth_pct": round(depth, 2),
                                  "days_below": len(below_idx),
                                  "reclaim_date": recent15[max(below_idx) + 1]["date"] if max(below_idx) + 1 < len(recent15) else last["date"],
                                  "burst": burst}

    # 收盘位置%：收盘价落在当日高低区间的位置（100=收最高点）
    rng = last["h"] - last["l"]
    range_pos = round((last["c"] - last["l"]) / rng * 100) if rng > 0 else None

    # 二次/三次探底未破前低（2026-07-11 Vic："反弹框架不好用，你可以选出oversold但是二次和三次测底
    # 没有破的吗"）——W底/三重底雏形，比单日反转日雏形更硬的结构证据。
    # 算法：近20根里找局部低点（低于左右邻居），取相邻间隔≥3根的低点序列；
    # 最近一个低点 ≥ 前一个低点×0.99（允许1%以内的undercut，超过算破位）且当前收盘已从最近低点抬起
    double_bottom = None
    if len(bars) >= 22:
        win = bars[-20:]
        pivots = []
        for i in range(1, len(win) - 1):
            if win[i]["l"] < win[i - 1]["l"] and win[i]["l"] <= win[i + 1]["l"]:
                if not pivots or i - pivots[-1][0] >= 3:
                    pivots.append((i, win[i]["l"], win[i]["date"]))
        if len(pivots) >= 2:
            (i1, l1, d1), (i2, l2, d2) = pivots[-2], pivots[-1]
            if l2 >= l1 * 0.99 and last["c"] > l2:
                double_bottom = {"low1": round(l1, 2), "low1_date": d1,
                                 "low2": round(l2, 2), "low2_date": d2,
                                 "undercut": l2 < l1,
                                 "triple": len(pivots) >= 3 and pivots[-3][1] * 0.99 <= l1}

    # 距52周高% 和 YTD%（2026-07-15加，oversold表F改版要用）。
    # 52周高用可得bars里最近252根的最高高点（bars不足252根时按可得范围近似）；
    # YTD用上一年最后一个收盘作基准，bars里没有上一年数据（新股）则为None
    hi52 = max(b["h"] for b in bars[-252:])
    off_52w_high_pct = round((last["c"] - hi52) / hi52 * 100, 2) if hi52 else None
    year = last["date"][:4]
    prev_year_closes = [b["c"] for b in bars if b["date"][:4] < year]
    ytd_pct = round(pct(last["c"], prev_year_closes[-1]), 2) if prev_year_closes else None

    # 10日结构（用最近10根完整K线）
    down_days = lower_lows = above20 = None
    if len(bars) >= 11:
        last10 = bars[-10:]
        down_days = sum(1 for i in range(len(last10)) if last10[i]["c"] < (bars[-11:][i]["c"]))
        lower_lows = sum(1 for i in range(1, 10) if last10[i]["l"] < last10[i - 1]["l"])
        if ma20:
            # 每根K线相对"当时的20MA"太贵，简化为相对当前20MA——判断结构够用
            above20 = sum(1 for b in last10 if b["c"] > ma20)

    return {
        "date": last["date"],
        "close": round(last["c"], 3),
        "open_pct": round(pct(last["o"], prev_c), 2) if prev_c else None,
        "high_pct": round(pct(last["h"], prev_c), 2) if prev_c else None,
        "low_pct": round(pct(last["l"], prev_c), 2) if prev_c else None,
        "t1_pct": round(pct(last["c"], prev_c), 2) if prev_c else None,
        "d5_pct": round(pct(closes[-1], closes[-6]), 2) if len(closes) >= 6 else None,
        "d21_pct": round(pct(closes[-1], closes[-22]), 2) if len(closes) >= 22 else None,
        "off_52w_high_pct": off_52w_high_pct,
        "ytd_pct": ytd_pct,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma50": round(ma50, 2) if ma50 else None,
        "ma200": round(ma200, 2) if ma200 else None,
        "dist_ma20_pct": round(pct(last["c"], ma20), 2) if ma20 else None,
        "dist_ma50_pct": round(pct(last["c"], ma50), 2) if ma50 else None,
        "dist_ma200_pct": round(pct(last["c"], ma200), 2) if ma200 else None,
        "ma20_slope_up": (ma20 > ma20_prev5) if (ma20 and ma20_prev5) else None,
        "ma150": round(ma150, 2) if ma150 else None,
        "ma150_slope_pct": round(ma150_slope, 2) if ma150_slope is not None else None,
        "weinstein_stage": weinstein_stage(last["c"], ma150, ma150_slope),
        "atr14": round(atr, 3) if atr else None,
        "atr14_pct": round(atr / last["c"] * 100, 2) if atr else None,
        "dist_ma20_atr": round((last["c"] - ma20) / atr, 2) if (ma20 and atr) else None,
        "dist_ma50_atr": round((last["c"] - ma50) / atr, 2) if (ma50 and atr) else None,
        "ema9": round(ema9, 2) if ema9 else None,
        "dist_ema9_pct": round(pct(last["c"], ema9), 2) if ema9 else None,
        "ema20": round(ema20, 2) if ema20 else None,
        "dist_ema20_pct": round(pct(last["c"], ema20), 2) if ema20 else None,
        "range5_pct": range5_pct,
        "range5_atr": range5_atr,
        # 2026-07-23加：执行转换表(report_helpers.exec_rows)拿它们定触发价和止损，
        # 之前只算了range5_pct没存原始值，导致下游要重新拉K线
        "hi5": round(hi5, 2) if hi5 else None,
        "lo5": round(lo5, 2) if lo5 else None,
        "tight_5d": (range5_pct is not None and range5_pct < 8.0 and (range5_atr is None or range5_atr < 2.0)),
        "vol_ratio": vol_ratio,
        "undercut_rally": undercut_rally,
        "breakout_pullback": breakout_pullback,
        "shakeout_burst": shakeout_burst,
        "double_bottom": double_bottom,
        "rsi14": round(rsi14(closes), 1) if rsi14(closes) is not None else None,
        "range_pos": range_pos,
        "down_days_10": down_days,
        "lower_lows_10": lower_lows,
        "above_ma20_10": above20,
        "bars": len(bars),
    }


def extension_level(m):
    """延伸度判断（2026-07-07加，Vic：'XBI似乎都很extended'）。ATR口径，分四档，
    并直接决定允许哪类setup：extreme=不建新仓等深度回踩；high=只允许回踩类（Setup A/D），
    禁止追突破（Setup B）；mild/ok=全部setup可用。"""
    d50, d20, rsi = m.get("dist_ma50_atr"), m.get("dist_ma20_atr"), m.get("rsi14")
    reasons = []
    if d50 is not None and d50 >= 4: reasons.append(f"距50MA {d50}ATR")
    if rsi is not None and rsi >= 80: reasons.append(f"RSI {rsi}")
    if reasons:
        return "extreme", reasons
    if d50 is not None and d50 >= 2.5: reasons.append(f"距50MA {d50}ATR")
    if rsi is not None and rsi >= 72: reasons.append(f"RSI {rsi}")
    if d20 is not None and d20 >= 2: reasons.append(f"距20MA {d20}ATR")
    if reasons:
        return "high", reasons
    if (d50 is not None and d50 >= 1.5) or (d20 is not None and d20 >= 1.2):
        return "mild", [f"距50MA {d50}ATR / 距20MA {d20}ATR"]
    return "ok", []


def unilateral_score(m):
    """单边板块打分：对应CONTEXT.md「单边板块确认条件」第2条的结构化标准。
    满分4：跌天数≤4 / 无低点破坏（lower_lows≤3，回调不破前低的宽松版）/ 站稳20MA（10日里≥8天）/ RSI≥50且20MA上翘。"""
    if m["down_days_10"] is None:
        return None, []
    checks = {
        "跌天数≤4": m["down_days_10"] <= 4,
        "低点未破坏": (m["lower_lows_10"] or 0) <= 3,
        "站稳20MA": (m["above_ma20_10"] or 0) >= 8,
        "RSI强势+MA上翘": (m["rsi14"] or 0) >= 50 and bool(m["ma20_slope_up"]),
    }
    return sum(checks.values()), [k for k, v in checks.items() if v]


# ---------------- 台账维护 ----------------
def load_json(path, default):
    if Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return default


# 🔴 2026-08-13：仓库转公开 GitHub 仓库，凭证从代码里移出。
#    这里原本是明文 key，注释还写着「key本来就明文记在CONTEXT.md」——
#    **公开仓库里那等于把 key 送人**，而且它已经进过 10 个提交的历史，所以当天做了历史清洗。
#    取值顺序：环境变量 ADANOS_API_KEY → 仓库根 .secrets.json（已在 .gitignore）。
#    两个都没有就返回 None，fetch_adanos() 跳过并在报告里标「未取到」，不会让整条管线挂掉。
def _load_secret(name: str):
    import os
    v = os.environ.get(name)
    if v:
        return v
    p = ROOT / ".secrets.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")).get(name)
        except Exception:
            return None
    return None


ADANOS_KEY = _load_secret("ADANOS_API_KEY")

# Vic自建的宏观数据表（2026-07-12，GOOGLEFINANCE实时公式，链接共享只读）——替代大部分WebFetch宏观查询。
# 当前行：VIX短期期货(VIXY代理)/VIX(INDEXCBOE:VIX本体!)/USO(油代理)/BTCUSD/美元指数ETF(UUP代理)
VIC_MACRO_SHEET = "https://docs.google.com/spreadsheets/d/1pHuQkNgP9NPrzAq4ALPvyQ-Awmwh2Qr7OCESEdcKZG0/gviz/tq?tqx=out:csv&gid=0"
# S&P500全量市宽仪表盘（Vic主Sheet的新tab，2026-07-21接入）——注意用export?format=csv走gid，
# gviz接口对这种多段不规则表格会丢列，不要换回gviz
SP500_BREADTH_SHEET = "https://docs.google.com/spreadsheets/d/1zXbIfknybtivC5hgkqthyhqwK9OjYCKVadvJTPZrHqE/export?format=csv&gid=90181001"
# Stockbee公开表（T2108 + 4%涨跌 + 5日/10日ratio + 二级中期口径）。
# 2026-07-23接入fetch管线——**在此之前一直是每天手动curl看一眼就扔，历史序列从没被保存过，
# 导致"季度/月度中期口径"这一整层的趋势判断长期缺失**（Vic拿着这张表指出：SPY风平浪静但
# 个股很多腰斩，实测S&P一个月+0.34%而季度涨25%净值从+472塌到-26）。
STOCKBEE_SHEET = "https://docs.google.com/spreadsheets/d/1O6OhS7ciA8zwfycBfGPbP2fWJnR0pn2UUvFZVDP9jpE/pub?output=csv"
# Vic主Sheet的"Maket breath"tab（原名拼写有误，勿改）——SPX/NDX/IWM的>20MA(TW)/>50MA(FI)历史。
# 2026-07-27新增自动抓取：给市宽表提供"前一日"对照列（Vic："B·市宽这个表格增加前一日的值"）。
MAKET_BREATH_SHEET = ("https://docs.google.com/spreadsheets/d/1zXbIfknybtivC5hgkqthyhqwK9OjYCKVadvJTPZrHqE"
                       "/gviz/tq?tqx=out:csv&sheet=Maket%20breath")
# COMBINED U.S. MARKET BREADTH（2026-07-27 Vic新增的tab，gid=90181401）——
# 口径从旧的"S&P500 only"(gid=90181001)扩成 S&P500 + NASDAQ100 + Russell2000 + Dow30 去重共2469只。
# ⚠️live块是**当日盘中**快照(Status=LIVE)，盘前报告绝不能用（那是未来函数）；
# 盘前一律取history块里"上一个完整交易日"那一行，盘后才用live块。
COMBINED_BREADTH_SHEET = ("https://docs.google.com/spreadsheets/d/1zXbIfknybtivC5hgkqthyhqwK9OjYCKVadvJTPZrHqE"
                          "/export?format=csv&gid=90181401")


def fetch_vic_macro_sheet():
    """读Vic的宏观数据表 → {名称: 数值}。失败返回error字段，报告侧退回WebFetch。"""
    import csv
    import io
    import urllib.request
    try:
        raw = urllib.request.urlopen(VIC_MACRO_SHEET, timeout=30).read().decode("utf-8")
        out = {}
        for row in csv.reader(io.StringIO(raw)):
            if len(row) >= 2 and row[0].strip():
                try:
                    out[row[0].strip()] = float(row[1].replace(",", ""))
                except ValueError:
                    out[row[0].strip()] = row[1].strip()
        return out
    except Exception as e:
        return {"error": str(e)}


def fetch_stockbee(days: int = 40):
    """Stockbee公开表 → 结构化历史序列（newest first）。

    **一级指标**（原本就在用）：T2108 / 4%涨跌家数 / 5日·10日ratio —— 全是短期口径。
    **二级指标**（2026-07-23才接进来）：季度涨跌25%+ / 月内涨跌25%+ / 月内涨跌50%+ / 34日涨跌13%+
    —— 中期口径，衡量的是"到底有多少股票在真的赚钱/亏钱"，跟指数经常背离。

    列顺序按表格固定位置解析（Vic不改这张表，它是第三方公开发布的）。
    """
    import csv
    import io
    import urllib.request

    def num(s):
        try:
            return float(str(s).replace(",", "").strip())
        except (ValueError, AttributeError):
            return None

    try:
        raw = urllib.request.urlopen(STOCKBEE_SHEET, timeout=30).read().decode("utf-8")
        rows = list(csv.reader(io.StringIO(raw)))
        out = []
        for r in rows:
            if not r or "/" not in str(r[0]):
                continue
            if len(r) < 16:
                continue
            out.append({
                "date": r[0].strip(),
                "up4": num(r[1]), "dn4": num(r[2]),
                "ratio5": num(r[3]), "ratio10": num(r[4]),
                "q_up25": num(r[5]), "q_dn25": num(r[6]),
                "m_up25": num(r[7]), "m_dn25": num(r[8]),
                "m_up50": num(r[9]), "m_dn50": num(r[10]),
                "d34_up13": num(r[11]), "d34_dn13": num(r[12]),
                "universe": num(r[13]), "t2108": num(r[14]), "spx": num(r[15]),
            })
            if len(out) >= days:
                break
        return {"rows": out}
    except Exception as e:
        return {"error": str(e)}


def fetch_maket_breath(days: int = 10):
    """"Maket breath"tab → 结构化历史序列（newest first）：SPX/NDX/IWM的>20MA(TW)/>50MA(FI)。
    2026-07-27新增。用途=市宽表的「前一日」对照列。"""
    import csv
    import io
    import urllib.request

    def num(s):
        try:
            return float(str(s).replace(",", "").strip())
        except (ValueError, AttributeError):
            return None

    try:
        raw = urllib.request.urlopen(MAKET_BREATH_SHEET, timeout=30).read().decode("utf-8")
        rows = list(csv.reader(io.StringIO(raw)))
        out = []
        for r in rows[1:]:  # 跳过表头
            if not r or not r[0].strip():
                continue
            try:
                out.append({
                    "date": r[0].strip(),
                    "s5tw": num(r[1]), "s5fi": num(r[2]),
                    "ndtw": num(r[3]), "ndfi": num(r[4]),
                    "r2tw": num(r[5]), "r2fi": num(r[6]),
                })
            except IndexError:
                continue
            if len(out) >= days:
                break
        return {"rows": out}
    except Exception as e:
        return {"error": str(e)}


def family_correlations(bars_by_ticker: dict, window: int = 60):
    """板块家族内两两相关系数（2026-07-27新增，Vic："我想xle不好，xop oih会联动吧"）。

    实测结果说明**不能按family名义一刀切**——同一个family里差异极大：
      energy: XOP↔XLE 0.94（几乎同一标的）但 OIH↔XLE 只有0.64（7/27停火当天确实分道扬镳，
              XLE -2.52% 而 OIH +0.07%）
      health: PPH↔XLV 0.91 但 XBI↔XLV 只有0.32
      tech:   AIQ↔XLK 0.97 / QTUM 0.94，但 IGV 只有0.31
    所以判据用**实测相关系数≥0.85**，不用"是不是同一个family"。
    """
    import itertools
    from report_helpers import SECTOR_FAMILY  # noqa: PLC0415

    def rets(t):
        b = bars_by_ticker.get(t)
        if not b or len(b) < window + 1:
            return None
        c = [x["c"] for x in b][-(window + 1):]
        return [(c[i] - c[i - 1]) / c[i - 1] for i in range(1, len(c))]

    def corr(a, b):
        n = min(len(a), len(b))
        if n < 20:
            return None
        a, b = a[-n:], b[-n:]
        ma, mb = sum(a) / n, sum(b) / n
        num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
        da = sum((x - ma) ** 2 for x in a) ** .5
        db = sum((x - mb) ** 2 for x in b) ** .5
        return round(num / (da * db), 3) if da and db else None

    out = {}
    for tks in SECTOR_FAMILY.values():
        for a, b in itertools.combinations(tks, 2):
            ra, rb = rets(a), rets(b)
            if ra and rb:
                c = corr(ra, rb)
                if c is not None:
                    out["%s|%s" % (a, b)] = c
    return out


def fetch_combined_breadth(days: int = 25):
    """COMBINED U.S. MARKET BREADTH tab（2026-07-27接入）→ {live, stages, score, history}。

    live/stages/score 来自表顶的**当日盘中**块；history 是逐日结算行（newest first），
    含 New Highs/Lows、Advance/Decline、Up-Open/Down-Open、Up/Down Volume、Stage2%、Stage4%、Daily Score。
    **盘前只能用 history[0]（上一完整交易日）**；live块留给盘后。
    """
    import csv
    import io
    import urllib.request

    def num(s):
        try:
            return float(str(s).replace(",", "").replace("%", "").strip())
        except (ValueError, AttributeError):
            return None

    try:
        raw = urllib.request.urlopen(COMBINED_BREADTH_SHEET, timeout=30).read().decode("utf-8")
        rows = list(csv.reader(io.StringIO(raw)))
        cells = [[c.strip() for c in r] for r in rows]

        def find(label, col0=0):
            for r in cells:
                if r and r[col0].strip() == label:
                    return [c for c in r if c != ""]
            return []

        live, stages, score, history = {}, {}, {}, []
        for name in ("New Highs vs New Lows", "Advance vs Decline", "Up from Open vs Down",
                     "Up on Volume vs Down on Volume", "Up 4% vs Down 4%"):
            r = find(name)
            if len(r) >= 6:
                live[name] = {"positive": num(r[1]), "negative": num(r[2]),
                              "positive_pct": num(r[3]), "net": num(r[4]), "signal": r[5]}
        for st in ("Stage 1", "Stage 2", "Stage 3", "Stage 4"):
            r = find(st)
            if len(r) >= 3:
                stages[st] = {"count": num(r[1]), "share_pct": num(r[2])}
        r = find("MARKET SCORE")
        if len(r) >= 6:
            score = {"score": r[1], "regime": r[3], "risk_mode": r[5]}

        hi = next((i for i, r in enumerate(cells)
                   if r and r[0].strip() == "Date" and "New Highs" in r), None)
        if hi is not None:
            for r in cells[hi + 1:]:
                if not r or not r[0].strip() or "-" not in r[0]:
                    continue
                v = [c for c in r if c != ""]
                if len(v) < 13:
                    continue
                history.append({
                    "date": v[0], "new_highs": num(v[1]), "new_lows": num(v[2]),
                    "advance": num(v[3]), "decline": num(v[4]), "advance_pct": num(v[5]),
                    "up_open": num(v[6]), "down_open": num(v[7]),
                    "up_volume": num(v[8]), "down_volume": num(v[9]),
                    "stage2_pct": num(v[10]), "stage4_pct": num(v[11]), "daily_score": num(v[12]),
                })
                if len(history) >= days:
                    break
        meta = find("COMBINED U.S. MARKET BREADTH")
        return {"live": live, "stages": stages, "score": score, "history": history,
                "meta": meta[1] if len(meta) > 1 else ""}
    except Exception as e:
        return {"error": str(e)}


def fetch_sp500_breadth():
    """Vic的Google Sheet新增tab「S&P 500 LIVE MARKET BREADTH」（2026-07-21接入，Vic:"增加了更多
    market breath数据，很有价值"）→ 全量500只的市宽仪表盘，数据源同为Longbridge OpenAPI。

    返回 {"live": {...}, "stages": [...], "history": [...]}，失败返回{"error": ...}。
    按标记文字定位各段（不写死行号，Vic改表时不会一改就崩）：
      live    5项指标(New Highs/Advance/Up from Open/Up on Volume/Up 4%) + MARKET SCORE/REGIME/RISK MODE
      stages  Weinstein四阶段分类计数（Stage 2=上升趋势 / Stage 4=下降趋势）
      history 近1个月逐日（newest first），含Daily Score与Stage2%/Stage4%趋势
    """
    import csv
    import io
    import urllib.request

    def num(s):
        s = str(s).strip().replace(",", "").replace("%", "")
        if not s:
            return None
        try:
            return float(s) if "." in s else int(s)
        except ValueError:
            return None

    try:
        raw = urllib.request.urlopen(SP500_BREADTH_SHEET, timeout=30).read().decode("utf-8")
        rows = list(csv.reader(io.StringIO(raw)))

        def cell(r, i):
            return r[i].strip() if len(r) > i else ""

        live = {"metrics": [], "status": "", "updated": "", "session": ""}
        stages, history = [], []
        hist_hdr = None

        for r in rows:
            c0 = cell(r, 0)
            if c0 in ("New Highs vs New Lows", "Advance vs Decline", "Up from Open vs Down",
                      "Up on Volume vs Down on Volume", "Up 4% vs Down 4%"):
                live["metrics"].append({
                    "metric": c0, "positive": num(cell(r, 1)), "negative": num(cell(r, 2)),
                    "positive_pct": cell(r, 3), "net": num(cell(r, 4)), "signal": cell(r, 5)})
                # 右侧COVERAGE键值对(Session/Universe/Received/Stale/Status)散落在6/7列
                k, v = cell(r, 6), cell(r, 7)
                if k == "Session":
                    live["session"] = v
                elif k == "Status":
                    live["status"] = v
            elif c0 == "MARKET SCORE":
                live["score"] = cell(r, 2)
                live["regime"] = cell(r, 6)
                live["risk_mode"] = cell(r, 10)
            elif c0.startswith("Stage ") and num(cell(r, 2)) is not None:
                stages.append({"stage": c0, "count": num(cell(r, 2)), "share": cell(r, 4)})
                if cell(r, 6) == "Updated (ET)":
                    live["updated"] = cell(r, 9)
            elif c0 == "Classified Total":
                live["classified"] = num(cell(r, 2))
                if cell(r, 6) == "Updated (ET)":
                    live["updated"] = cell(r, 9)
            elif cell(r, 6) == "Updated (ET)" and cell(r, 9):
                live["updated"] = cell(r, 9)
            elif c0 == "Date" and cell(r, 1) == "New Highs":
                hist_hdr = True
            elif hist_hdr and re.match(r"\d{4}-\d{2}-\d{2}$", c0):
                history.append({
                    "date": c0, "new_highs": num(cell(r, 1)), "new_lows": num(cell(r, 2)),
                    "advance": num(cell(r, 3)), "decline": num(cell(r, 4)),
                    "advance_pct": cell(r, 5), "up_open": num(cell(r, 6)),
                    "down_open": num(cell(r, 7)), "up_volume": num(cell(r, 8)),
                    "down_volume": num(cell(r, 9)), "stage2_pct": cell(r, 10),
                    "stage4_pct": cell(r, 11), "score": num(cell(r, 12))})

        if not live["metrics"] and not history:
            return {"error": "parsed 0 rows — sheet layout may have changed"}
        return {"live": live, "stages": stages, "history": history}
    except Exception as e:
        return {"error": str(e)}


def fetch_adanos(metrics_by_ticker):
    """Adanos热度异动榜（2026-07-07重做，Vic：'扫来扫去都那几只，有点鸡肋，专注热度变化或结合涨跌异动'）。
    不再输出静态Top100，改算每只的buzz_score相对自己近7日均值的变化率，只报『热度暴增』的：
    新面孔进榜、或buzz较基线+50%以上。再join价格数据（若在监控范围内）看是否伴随真实涨跌异动。"""
    import urllib.request
    if not ADANOS_KEY:
        # 2026-08-13：凭证移出仓库后，没配 key 时安静跳过而不是抛异常——
        # 报告里会渲染成「未取到」，整条管线不受影响。
        return {"error": "未配置 ADANOS_API_KEY（环境变量或 .secrets.json），本次跳过"}
    try:
        req = urllib.request.Request(
            "https://api.adanos.org/x/stocks/v1/trending?limit=100",
            headers={"X-API-Key": ADANOS_KEY})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        return {"error": str(e)}
    items = data if isinstance(data, list) else data.get("data") or data.get("stocks") or []
    surges, steady_top = [], []
    for it in items:
        t = it.get("ticker", "")
        buzz = it.get("buzz_score") or 0
        hist = it.get("trend_history") or []
        prior = [h for h in hist[:-1] if isinstance(h, (int, float))]
        baseline = sum(prior) / len(prior) if prior else None
        if baseline and baseline > 0:
            delta_pct = round((buzz - baseline) / baseline * 100, 1)
            is_new = False
        else:
            delta_pct, is_new = None, True  # 无历史=新进榜
        m = metrics_by_ticker.get(t)
        row = {"ticker": t, "buzz": buzz, "buzz_delta_pct": delta_pct, "new_entry": is_new,
               "trend": it.get("trend"), "mentions": it.get("mentions"),
               "bullish_pct": it.get("bullish_pct"),
               "t1_pct": m["t1_pct"] if m else None}
        if is_new or (delta_pct is not None and delta_pct >= 50):
            surges.append(row)
        steady_top.append(row)
    surges.sort(key=lambda x: -(x["buzz_delta_pct"] if x["buzz_delta_pct"] is not None else 999))
    return {"surges": surges[:10],
            "top5_steady": [r["ticker"] for r in sorted(steady_top, key=lambda x: -(x["buzz"] or 0))[:5]]}


def hit_stats():
    """扫全部盘后JSON算滚动命中率。样本少时如实输出样本数，不硬算百分比趋势。"""
    entries = []
    for f in sorted(glob.glob(str(DAILY_DIR / "*-postmarket.json"))):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            entries.append({"date": d.get("date"), "hit": d.get("hit_count", 0),
                            "partial": d.get("partial_count", 0), "miss": d.get("miss_count", 0)})
        except Exception:
            continue
    def agg(items):
        h = sum(x["hit"] for x in items); p = sum(x["partial"] for x in items); m = sum(x["miss"] for x in items)
        total = h + p + m
        return {"hit": h, "partial": p, "miss": m, "days": len(items),
                "rate": f"{h / total * 100:.0f}%" if total else "-"}
    cutoff30 = (date.today() - timedelta(days=30)).isoformat()
    return {
        "week": agg(entries[-5:]),
        "rolling30": agg([e for e in entries if (e["date"] or "") >= cutoff30]),
        "all_days": len(entries),
    }


def price_x_watch(metrics_by_ticker, ctx):
    """给X台账每条提及补最新价和涨跌幅。台账里的票不一定在主universe里，缺的单独拉。"""
    ledger = load_json(X_WATCH_PATH, {"entries": []})
    out = []
    for e in ledger.get("entries", []):
        t = e["ticker"]
        m = metrics_by_ticker.get(t)
        if m is None:
            bars = fetch_bars(ctx, t, 30)
            m = analyze(bars) if bars else None
        row = dict(e)
        if m:
            row["last_close"] = m["close"]
            row["pct_since"] = round(pct(m["close"], e["ref_price"]), 2) if e.get("ref_price") else None
        out.append(row)
    return out


def update_signal_history(metrics_by_ticker):
    """append当天盘前信号灯状态；回填缺失的次日结果（用SPY/QQQ的T-1%）。"""
    hist = load_json(SIGNAL_HISTORY_PATH, {"entries": []})
    today = date.today().isoformat()
    pre_path = DAILY_DIR / f"{today}-premarket.json"
    if pre_path.exists() and not any(e["date"] == today for e in hist["entries"]):
        pre = json.loads(pre_path.read_text(encoding="utf-8"))
        sl = pre.get("signal_light", {})
        hist["entries"].append({
            "date": today,
            "bias": sl.get("bias", {}).get("level"), "bond": sl.get("bond", {}).get("level"),
            "dxy": sl.get("dxy", {}).get("level"), "breadth": sl.get("breadth", {}).get("level"),
            "spy_next_pct": None, "qqq_next_pct": None,
        })
    # 回填：最近一条没有结果、且其日期早于最新交易日的，填上最新T-1%
    spy, qqq = metrics_by_ticker.get("SPY"), metrics_by_ticker.get("QQQ")
    if spy and qqq:
        for e in hist["entries"]:
            if e["spy_next_pct"] is None and e["date"] < spy["date"]:
                e["spy_next_pct"], e["qqq_next_pct"] = spy["t1_pct"], qqq["t1_pct"]
                e["outcome_date"] = spy["date"]
    SIGNAL_HISTORY_PATH.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(hist["entries"])


# ---------------- SDK ----------------
def fetch_bars(ctx, ticker, count):
    from longport.openapi import Period, AdjustType
    sym = f"{ticker}.US"
    try:
        raw = ctx.candlesticks(sym, Period.Day, count, AdjustType.NoAdjust)
        time.sleep(0.12)  # 控制调用频率
        return [{"date": str(b.timestamp)[:10], "o": float(str(b.open)), "h": float(str(b.high)),
                 "l": float(str(b.low)), "c": float(str(b.close)), "v": float(str(b.volume))} for b in raw]
    except Exception as e:
        print(f"  [skip] {ticker}: {e}")
        return None


def main():
    quick = "--quick" in sys.argv
    from longport.openapi import QuoteContext, Config
    ctx = QuoteContext(Config.from_apikey_env())

    tickers = universe(quick)
    print(f"fetching {len(tickers)} tickers (quick={quick}) ...")
    metrics, bars_by = {}, {}
    for t in tickers:
        bars = fetch_bars(ctx, t, BARS_NEEDED)
        if bars:
            metrics[t] = analyze(bars)
            bars_by[t] = bars

    # 单边板块排行榜
    scan = []
    for t in SECTOR_SCAN:
        m = metrics.get(t)
        if not m:
            continue
        score, passed = unilateral_score(m)
        if score is not None:
            ext, ext_reasons = extension_level(m)
            scan.append({"ticker": t, "score": score, "passed": passed, "d5_pct": m["d5_pct"],
                         "d21_pct": m["d21_pct"], "rsi14": m["rsi14"], "dist_ma50_atr": m["dist_ma50_atr"],
                         "down_days_10": m["down_days_10"],
                         "extension": ext, "extension_reasons": ext_reasons})
    scan.sort(key=lambda x: (-x["score"], -(x["d5_pct"] or -999)))

    # 闸门线参考（周一重算用）。ATR版为主（Vic熟ATR不熟SD），SD版保留作对照。
    gates = {}
    for t in ["VOO", "SPY", "QQQ", "IWM"]:
        m = metrics.get(t)
        if m and m["ma20"]:
            bars = fetch_bars(ctx, t, 25)
            closes = [b["c"] for b in bars] if bars else []
            sd = stdev(closes, 20)
            a = m.get("atr14")
            gates[t] = {"ma20": m["ma20"], "ma50": m["ma50"], "atr14": a,
                        "ma20_plus_1atr": round(m["ma20"] + a, 2) if a else None,
                        "ma20_minus_1atr": round(m["ma20"] - a, 2) if a else None,
                        "plus_1sd": round(m["ma20"] + sd, 2) if sd else None,
                        "minus_1sd": round(m["ma20"] - sd, 2) if sd else None}

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_date": metrics.get("SPY", {}).get("date"),
        "quick": quick,
        "metrics": metrics,
        "unilateral_scan": scan,
        "gate_reference": gates,
        "hit_stats": hit_stats(),
        "adanos_movers": fetch_adanos(metrics),
        "x_watch_performance": price_x_watch(metrics, ctx),
        "signal_history_entries": update_signal_history(metrics),
        "macro_sheet": fetch_vic_macro_sheet(),
        "sp500_breadth": fetch_sp500_breadth(),
        "stockbee": fetch_stockbee(),
        "maket_breath": fetch_maket_breath(),
        "combined_breadth": fetch_combined_breadth(),
        "family_corr": family_correlations(bars_by),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"market_{date.today().strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out_path}  (tickers={len(metrics)}, data_date={out['data_date']})")
    print("top unilateral candidates:")
    for s in scan[:8]:
        ext = s["extension"]
        ext_str = f"  [{ext.upper()}: {'; '.join(s['extension_reasons'])}]" if ext not in ("ok",) else ""
        print(f"  {s['ticker']:6} score={s['score']}/4  5d={s['d5_pct']}%  RSI={s['rsi14']}  50MA={s['dist_ma50_atr']}ATR{ext_str}")


if __name__ == "__main__":
    main()
