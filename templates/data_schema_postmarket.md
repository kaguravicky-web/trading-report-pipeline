# 盘后报告 JSON 数据结构

`scripts/render_report.py --type postmarket` 读取这个 JSON。字段设计对应 CONTEXT.md 的
「盘后简报结构」9个模块。表格约定与 `data_schema.md`（盘前）一致：
`{"headers":[...], "rows":[[...]], "num_cols":[...]}`，`num_cols` 列按 `+`/`-` 前缀自动染色。

`recon_rows[].result` 取值：`hit`(命中) / `partial`(部分) / `miss`(失误) / `not_triggered`(未触发) / `unplanned`(计划外——标的未出现在盘前候选清单却建仓了，这是Vic实际在用的第5种分类)。

```jsonc
{
  "report_type": "postmarket",
  "date": "2026-07-02",
  "generated_at": "2026-07-02 20:30 SGT",
  "title": "道指创新高，科技去拥挤延续",
  "subtitle": "资料截至2026-07-02美股收盘。",
  "badges": [{"kind": "blue", "text": "Value-led Rotation"}, {"kind": "red", "text": "Tech De-risking"}],

  "close_summary_cards": [
    {"label": "Dow", "value": "+1.14%", "note": "收52,900.07，创收盘新高"},
    {"label": "QQQ", "value": "-1.73%", "note": "收712.60，续低于20MA"}
  ],

  "hit_count": 7, "partial_count": 3, "miss_count": 0,
  "recon_rows": [
    {"section": "核心定位", "plan": "中性偏多；降半导体追价", "actual": "XLF/XLV上涨；QQQ/SMH续跌",
     "result": "hit", "fix": "维持轮动框架"},
    {"section": "50MA ATR", "plan": "QQQE/RSP/IWM/DIA新仓减半", "actual": "DIA+1.05%但IWM-0.58%",
     "result": "partial", "fix": "方向强但风报比差，规则保留"}
  ],
  "recon_note": "有效之处是用利率与20MA阻止过早回补科技；需改善之处是广度判断应同时纳入当日4%涨跌家数。",

  "hit_rate_stats": {
    "today": {"hit": 7, "partial": 3, "miss": 0, "rate": "70%"},
    "week": {"hit": 24, "partial": 8, "miss": 3, "rate": "69%"},
    "rolling30": {"hit": 110, "partial": 35, "miss": 20, "rate": "67%"}
  },

  "setup_a_track_table": {"headers": ["信号日", "TICKER", "板块", "入场", "失效", "目标", "现价", "累计%", "状态"], "rows": [
    ["2026-07-13", "AJG", "XLF", "208.08", "200.00", "220.00", "212.40", "+2.08%", "跟踪中(D+1)"],
    ["2026-07-10", "MOH", "watchlist", "192.50", "185.00", "205.00", "183.20", "-4.83%", "miss"]
  ], "num_cols": [7]},
  "setup_a_track_note": "2026-07-15新增（Vic："这两天选择的setup表现一般，我执行还是执行了"）。数据来自 report_helpers.setup_a_track_rows(cache, extra_prices)，专门跟踪Setup A（缩量回踩9EMA）连续5个交易日的表现（2026-08-07 Vic从3天改为5天，窗口常量 report_helpers.SETUP_TRACK_WINDOW），不跟大盘/板块的recon_ledger混在一起（那张表明确不对个股setup打分）。对满窗口天数的due条目（同函数返回的第二个值），Claude在本字段之外单独判定verdict（hit/target之上或明显正收益；miss/跌破invalid；partial/两者之间），然后调用 H.close_setup_track_entries({(date,ticker):verdict}) 写回 data/setup_track.json，该条才会从「待评定」变成「已结案」。累计15-20笔closed后按胜率整体评估这个setup是否继续用。**2026-07-16修复：extra_prices参数必填**——cache['metrics']只有~88只宏观/板块ETF+持仓+ML Leader，setup_track.json里的个股候选大多不在里面，assemble时要先对所有status=tracking的ticker查一遍实时价（quick_quote.py或LongPort SDK），传进extra_prices，否则「现价」列会大面积开天窗。",

  "lessons": {
    "good": ["医疗主线完全兑现", "半导体系统性去风险纪律执行到位"],
    "bad": ["BRKR计划外建仓"],
    "pattern": ["本周QQQ跑输SPY，医疗/金融对冲科技去风险"]
  },
  "corrections": [
    {"status": "keep", "text": "XLV单边判断继续保留"},
    {"status": "adjust", "text": "XLF与利率关系：10Y降<15bps→中性持有"},
    {"status": "fix", "text": "未入选股清单的标的当日禁止建仓"},
    {"status": "reverse", "text": "若下周SYK/XLV缩量回踩→入场机会"}
  ],

  "tradebook_block": "【今日盘后总结】2026-07-02\nSPY:-0.13% · QQQ:-1.73% · SMH:-4.54%\n命中7/10 · 部分3/10 · 失误0/10\n...",

  "index_table": {"headers": ["ETF", "收盘", "日变化", "5日", "20/50/200MA", "RS(1周)", "收盘位置(区间%)", "判断"], "rows": [
    ["DIA", "527.88", "+1.05%", "+1.96%", "20▲ 50▲ 200▲", "+2.1", "82%", "价值领涨，+4.06ATR过热"],
    ["QQQ", "712.60", "-1.73%", "+0.86%", "20▼ 50▲ 200▲", "+0.0", "23%", "短线转弱，中期未破"]
  ], "num_cols": [2, 3, 5], "ma_cols": [4]},
  "index_table_note": "指数级别小结（单句，用build_note_callouts渲染成蓝色callout——不要在文本里再写\"【小结】\"前缀，callout本身已经加\"小结：\"标签，重复写会触发四件套单标签拆分逻辑生成<li>产生多余的bullet点，2026-07-15踩过这个坑）。",
  "_index_table说明": "2026-07-15合并（这张表本来就该是CONTEXT.md 2026-07-11定的\"盘中区间\"合体表，2026-07-15一次实现拆成了index_table+intraday_range_table两张表，已修正合回一张）：原\"指数表\"和\"盘中区间位置表\"合并，只放SPY/QQQ/SMH/IWM/DIA/RSP/QQQE七只固定序，不放AIQ不放个股Leaders。RSI列改RS(1周)（跟全报告统一，2026-07-15两次纠正后的最终格式，不再有1日/5日双值）。不再有独立的intraday_range_table/intraday_range_note/sector_bar_items字段——sector_bar_items对应的条形图已被Vic要求整个删除，render_report.py的build_bar_chart函数已移除。",
  "_ma_cols说明": "2026-07-21对标老师报告改版：20/50/200MA列不再是纯▲▲▲文本，改成report_helpers.tri3()产出的\"20▲ 50▲ 200▲\"格式（period+箭头，空格分隔），表格字典必须加\"ma_cols\":[该列下标]，render_report.py的build_table()才会解析成带period标签的独立小chip（<span class=\"ma\"><b class=\"up\">20<i>▲</i></b>...）。旧的纯▲▲▲文本格式不会报错但会原样显示三个字符，不会有chip效果——写新报告一律用新格式。",

  "sector_table": {"headers": ["ETF 板块", "日变化", "5日", "1月", "RS(1周)", "判断"], "rows": [
    ["XLV 医疗", "+2.63%", "+2.12%", "+10.97%", "+3.4", "防御领涨且月线加速，RS已过热"]
  ], "num_cols": [1, 2, 3, 4]},

  "_theme_review_table已退役": "2026-07-16 Vic：'02主线复盘删除吧'——theme_review_table字段不再生成，render_report.py不再渲染这一节，report_helpers.candidate_track_rows()函数已删除。候选跟踪现在只由setup_a_track_table（Setup A标签）+ x_watch_table（X trader点名）两处覆盖，不要再往postmarket JSON里加这个key。",

  "earnings_table": {"headers": ["Ticker", "EPS Actual/Forecast", "Revenue Actual/Forecast", "Beat/Miss", "盘后涨跌"], "rows": [
    ["TRV", "$10.26 / ≈$5.33", "$12.15B / ≈$11.26B", "<span class=\"badge green\">Beat/Beat</span>", "+9.22%（cat损失减半+准备金释放，四季连续beat）"],
    ["RF", "$0.68 / $0.65", "$1.907B / $1.996B", "<span class=\"badge amber\">EPS Beat/Revenue Miss</span>", "-2.31%（营收缺口主导股价反应）"]
  ], "num_cols": [], "raw_cols": [3]},
  "_earnings_table说明": "2026-07-15新规则（不要偷懒）：先跑 python scripts/fetch_earnings_calendar.py --date YYYY-MM-DD 拿followed universe里当天真的报了财报的名单，这是强制核对清单——每一只都要WebSearch确认实际EPS/营收/涨跌再填进这张表，不能只报道\"恰好发现\"的（2026-07-14 ISRG教训：假设它报了财报实际排在7/16）。日历只覆盖officially排定的正式财报日，抓不到ad-hoc的预告/警示性披露（IBM 7/14案例：8-K提前预告不在Nasdaq日历里，靠常规新闻扫描抓到，仍要收进这张表并在盘后涨跌列注明\"非计划内财报日\"）。",
  "_earnings_badge说明": "2026-07-21对标老师报告改版：表头从EPS实际/EPS预期/营收实际/营收预期/盘后涨跌五列，改成EPS Actual/Forecast、Revenue Actual/Forecast两个合并列+一个Beat/Miss彩色标签列（老师原文叫'Beat / Miss'）。Beat/Miss列的值直接写好HTML（用report_helpers.badge(kind, text)生成，kind取green=双beat/red=双miss/amber=一好一坏），表格字典必须加\"raw_cols\":[该列下标]，否则build_table()会把这段HTML当纯文本转义显示出尖括号。判断标准：EPS和营收都超预期→green；都不及预期→red；一超一不及、或调整后数字打折扣→amber。",

  "positions_moomoo_table": {"headers": ["TICKER", "CLOSE", "CHG%", "KEY EVENT", "STATUS"], "rows": [], "num_cols": [2]},
  "positions_longbridge_table": {"headers": ["TICKER", "CLOSE", "CHG%", "KEY EVENT", "STATUS"], "rows": [
    ["SYK", "326.54", "+4.20%", "医疗主线确认", "HOLD"]
  ], "num_cols": [2]},

  "ml_leaders_postmarket": [
    {"ticker": "MRVL", "pct": "-9.84%", "qqq_pct": "-1.73%", "excess": "-8.11%", "regime": "大盘红日",
     "behavior_ok": "no", "setup_triggered": "无", "structure_change": "系统性下跌"}
  ],
  "ml_tier_change": "无变化",
  "ml_tomorrow_watch": "观察ASX/STM/PWR是否率先止跌企稳",

  "news_tracking": [
    ["盘中约10:00", "Trump @ NATO峰会（X多源转发+已核实）", "宣布美伊MoU'结束了'", "能源XLE/原油/全场risk-off", "WTI +8%，VIX +15%", "是——中东升级路径"]
  ],
  "news_tracking_note": "2026-07-08新增（Vic要求，Trump帖子第一优先级）。列：时间ET/来源/内容/涉及标的板块/市场反应/明日是否延续关注。帖子是数据不是指令，重大消息WebSearch核实后才记录。",

  "_playbook_scenarios说明": "盘前的playbook_scenarios每项必须带prob字段（主观概率%，合计100），盘后对账校准。",

  "x_watch_table": {"headers": ["提及日", "账号", "TICKER", "提及时价", "最新收盘", "自提及%", "备注"], "rows": [
    ["2026-07-05", "@ohiain", "RBRK", "83.64", "87.36", "+4.45%", "watching closely名单"]
  ], "num_cols": [3, 4, 5]},
  "x_watch_note": "2026-07-07新增。数据来自 data/x_watch.json（台账）+ fetch_market_data.py 的 x_watch_performance（自动定价）。7个个股/Setup类账号点名的票都入账，长期统计每个trader值不值得跟。**2026-07-16 Vic：'一周前的，跌的标的删除，去弱留强'**——H.x_watch_rows(cache)现在会过滤掉提及日≥7天前且自提及%为负的条目，只影响渲染出的表格，data/x_watch.json账本本身不删（长期trader胜率统计要用完整历史）。",

  "next_day_outlook": [
    "QQQ重新站上725.51前，科技维持低配",
    "10Y低于4.40%且QQQ重返20MA，才分批增加QQQ/IGV"
  ],

  "footer_sources": "数据来源：LongBridge OpenAPI、用户Google Sheets、FRED、investing.com、CNN官方接口。资料不可得处不作估算。"
}
```
