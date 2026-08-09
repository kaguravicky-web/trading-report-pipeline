# 盘前报告 JSON 数据结构

`scripts/render_report.py` 读取这个 JSON，渲染成 `output/premarket/YYYY-MM-DD-premarket.html`。
每次触发「盘前」时，Claude 按 CONTEXT.md 的工作流拿到真实数据后，照这个结构写一份
`data/daily/YYYY-MM-DD-premarket.json`，再跑渲染脚本。

**表格约定**：所有表格用 `{"headers": [...], "rows": [[...], ...], "num_cols": [1,2,3]}` 的形式。
`num_cols` 是需要右对齐、且按 `+`/`-` 前缀自动染色（绿涨红跌）的列下标（从0开始）。不在 `num_cols`
里的列一律左对齐、不染色。单元格永远是字符串。

**颜色等级约定**：凡是 `level` 字段，取值只能是 `low` / `mid` / `high`（风险由低到高，对应绿/黄/红）。

```jsonc
{
  "date": "2026-07-04",
  "generated_at": "2026-07-04 20:15 SGT",
  "title": "报告主标题，一句话结论",
  "subtitle": "数据截止说明，比如市场资料截至美东XX:XX；广度数据截至上一交易日收盘",
  "badges": [
    {"kind": "green", "text": "Checklist 1/8 High · Low Risk"},
    {"kind": "amber", "text": "等待非农"}
  ],

  "signal_light": {
    "bias": {"level": "low", "label": "OFFENSE"},
    "bond": {"level": "low", "label": "CALM"},
    "dxy": {"level": "low", "label": "NEUTRAL"},
    "breadth": {"level": "low", "label": "BULLISH"},
    "discipline": "医疗XLV/金融XLF主线为主，半导体只持不追"
  },

  "scoreboard_rows": [
    {"condition": "10D breadth ratio >1.35（升级·2/3）", "type": "upgrade", "threshold": "1.35", "current": "1.49", "distance_pct": "+10.4%", "status": "met"},
    {"condition": "NDX>50MA >52%（升级·2/3）", "type": "upgrade", "threshold": "52%", "current": "56.86%", "distance_pct": "+9.3%", "status": "met"},
    {"condition": "SPY收盘 ≥$748（升级·2/3）", "type": "upgrade", "threshold": "748", "current": "734.20", "distance_pct": "-1.8%", "status": "unmet"},
    {"condition": "QQQ收盘 ≥$728（升级·2/3，与SPY分开单独记）", "type": "upgrade", "threshold": "728", "current": "721.02", "distance_pct": "-0.96%", "status": "unmet"},
    {"condition": "T2108 <50（降级·任一）", "type": "downgrade", "threshold": "50", "current": "51.95", "distance_pct": "+3.9%", "status": "safe"},
    {"condition": "VIX >22（降级·任一）", "type": "downgrade", "threshold": "22", "current": "15.81", "distance_pct": "-28.1%", "status": "safe"},
    {"condition": "10Y >4.50%（久期防线）", "type": "duration", "threshold": "4.50%", "current": "4.48%", "distance_pct": "-0.4%", "status": "safe"}
  ],
  "scoreboard_note": "升级条件2/4满足（SPY/QQQ收盘价均未确认），降级/防线条件均安全未触发，维持中性偏多不做全面进攻。",
  "_scoreboard_rows说明": "type取值 upgrade/downgrade/duration/techparity。status跟type强绑定：upgrade和techparity类型只能用met(绿·已满足)/unmet(灰·未满足)；downgrade和duration类型只能用triggered(红·已触发，坏消息)/safe(绿·安全未触发)。绝不能让'降级条件未触发'显示成模糊的灰色——那样看起来和'升级条件还没满足'一样，分不清方向。QQQ和SPY永远各占一行，不要合并成一行'科技标配'（这两个是独立可判断的阈值，各自触发独立有意义）。",

  "risk_checklist": [
    {"label": "S&P 500 overextension", "level": "mid", "detail": "VOO+1.26 ATR"},
    {"label": "Increasing downward momentum", "level": "mid", "detail": "晶片弱但广度未恶化"},
    {"label": "Top range breakdown", "level": "low", "detail": "VOO仍在20/50/200MA上"},
    {"label": "Technical deterioration", "level": "mid", "detail": "QQQ失守20MA"},
    {"label": "Market breadth worsening", "level": "low", "detail": "六项MA广度均>50%"},
    {"label": "VIX >20 / spike", "level": "low", "detail": "VIX约15.8"},
    {"label": "Breakout win rate down", "level": "mid", "detail": "晶片失速"},
    {"label": "Theme momentum weakening", "level": "high", "detail": "SMH/AIQ同步偏弱"}
  ],
  "risk_checklist_note": "3高/4中/1低，短线修正集中在AI硬件主题，中期趋势未受损。",

  "regime_triggers": {
    "upgrade": {"rule": "满足2/3才成立", "items": ["QQQ收复20MA 726.01并站上+1SD 728.90", "10Y跌破4.40%，DXY不反向急升", "5D breadth ratio维持>1.5且RSP/IWM守强"]},
    "downgrade": {"rule": "任一触发即成立", "items": ["SPY跌破-1SD 716.49", "QQQ跌破-1SD 684.14", "5D breadth ratio<1或VIX>20"]}
  },

  "breadth_table": {"headers": ["指标", "当前值", "5日前", "判断"], "rows": [
    ["SPX>20MA", "67.65%", "61.15%", "改善"], ["SPX>50MA", "67.06%", "63.34%", "中期偏多"],
    ["NDX>20MA", "56.86%", "44.55%", "短线修复"], ["NDX>50MA", "55.88%", "54.45%", "仍有背离"],
    ["IWM>20MA", "68.85%", "54.63%", "非常强"], ["IWM>50MA", "67.62%", "67.18%", "中期仍强"],
    ["T2108", "51.95", "48.19", "中性偏多"], ["5日breadth ratio", "1.92", "1.09", "改善"],
    ["10日breadth ratio", "1.46", "1.32", "改善"], ["4%+上涨股", "272", "214", "普通买盘"],
    ["4%+下跌股", "375", "283", "卖压增加"]
  ], "num_cols": []},

  "other_assets_table": {"headers": ["资产", "最新", "日变动", "信号"], "rows": [
    ["美债10Y", "4.48%", "约持平", "未破久期门槛"],
    ["VIX", "15.81", "-2.65%", "VIX9D=12.37，比值0.78 → Contango，短端不紧张"], ["DXY", "100.86", "持平", "NEUTRAL"],
    ["CNN Fear & Greed", "34.06", "-", "Fear区间"],
    ["黄金", "4175.70", "+1.25%", "-"], ["铜", "6.224", "+0.89%", "-"], ["WTI原油", "68.78", "+0.13%", "-"],
    ["BTC", "62735", "+0.33%", "-"], ["ETH", "1760.35", "+0.13%", "-"],
    ["KOSPI", "8088.34", "+5.76%", "-"], ["日经225", "69744.07", "+1.47%", "-"],
    ["恒生指数", "23350.03", "+1.28%", "-"], ["恒生科技", "4499.00", "+1.00%", "-"], ["上证指数", "4043.64", "+0.37%", "-"]
  ], "num_cols": [2]},
  "_other_assets说明": "美债2Y已删除（用户不看）。VIX9D不再单独占一行，折进VIX那行的'信号'列里判断contango/backwardation。**MOVE已彻底删除（2026-07-21 Vic："我实在抓不到，直接从报告删除吧"）——investing.com接口反复不可用，Vic确认放弃，以后表里不再留MOVE行，也不用再尝试抓取。** CNN Fear&Greed从原来的散文字段挪进这张表当一行。",
  "joint_signal_lines": [
    "联合信号: 无制约（利率未破久期门槛，DXY中性，VIX9D/VIX比值0.78偏Contango不紧张）",
    "覆盖指令: 无（说明：只有当利率与美元同时触发极端阈值时，才会强制把当日仓位纪律降档，目前未触发）"
  ],

  "macro_radar_table": {"headers": ["事件", "日期(美东)", "预期", "结果", "市场解读"], "rows": [
    ["六月非农", "2026-07-03", "+110K", "+57K", "就业明显降温，但非无条件利多"],
    ["失业率", "2026-07-03", "4.3%", "4.2%", "受劳动参与率下降影响，非纯粹改善"]
  ], "num_cols": []},
  "macro_radar_detail": "非农结构：平均时薪+0.3% MoM/+3.5% YoY（符合预期，工资通胀温和降温）；劳动参与率61.5%（前值61.8%，下降0.3ppt，解释了失业率回落而非招聘加速）；4-5月合计下修74K。数据来源：BLS。",

  "sector_rs_tables": [
    {"title": "第一组：XL标准板块+指数基准（15只，全量）", "headers": ["TICKER", "T-1%", "5日%", "1月%", "盘前", "驱动/原因", "RS(1日/5日)"], "rows": [["XLV", "+2.63%", "+4.10%", "+8.85%", "-0.02%", "非农弱化+降息预期受益，防御板块领涨", "+4.4/+5.2"]], "num_cols": [1, 2, 3, 4, 6], "row_highlights": [""]},
    {"title": "第二组：AI/科技/半导体/量子/网安/软件（11只，全量）", "headers": ["TICKER", "T-1%", "5日%", "1月%", "盘前", "驱动/原因", "RS(1日/5日)"], "rows": [["DRAM", "-7.94%", "-11.20%", "-3.40%", "+7.04%", "存储链大跌，盘前反弹不等于收盘确认", "-6.2/-9.8"]], "num_cols": [1, 2, 3, 4, 6], "row_highlights": ["warn"]},
    {"title": "第三组：航天/国防/能源/材料/加密/中国/医疗/零售/地产（27只，全量）", "headers": ["TICKER", "T-1%", "5日%", "1月%", "盘前", "驱动/原因", "RS(1日/5日)"], "rows": [["EWY", "-2.89%", "+1.30%", "+6.10%", "+5.42%", "韩国上一交易日实际下跌，盘前反弹需等收盘验证", "-1.2/-0.1"]], "num_cols": [1, 2, 3, 4, 6]}
  ],
  "unilateral_scan_table": {"headers": ["排名", "TICKER", "得分", "通过项", "5日%", "1月%", "RS(1日/5日)", "距50MA", "延伸档位"], "rows": [
    ["1", "XHS", "4/4", "跌天数≤4·低点未破坏·站稳20MA·RSI强势", "+4.99%", "+13.2%", "+2.1/+4.6", "9.96×ATR", "EXTREME（回踩类减半仓）"]
  ], "num_cols": [4, 5, 6], "row_highlights": ["warn"]},
  "unilateral_scan_note": "数据来自 scripts/fetch_market_data.py 的 unilateral_scan 输出（板块ETF按CONTEXT.md单边结构标准自动打分），只列得分≥3的前8名，每行必须带延伸档位（extreme/high/mild/ok）和距50MA的ATR倍数。2026-07-15 Vic改版：展示列是RS(1日/5日)不是RSI；距50MA≥5×ATR的行row_highlights标warn（整行红底）。Vic明确说他自己参考这个排行榜筛选，Claude不代替他挑票。",

  "_positions表说明": "持仓监控表2026-07-07起必须带『持有理由』和『失效条件/论点检查』列，内容从 data/positions.json 读取并核对当天是否触发失效（见CONTEXT.md「持仓论点跟踪」）。headers参考：[\"TICKER\",\"现价\",\"成本\",\"P&L%\",\"持有理由\",\"失效条件\",\"论点检查\"]。",

  "_sector_rs_tables说明": "三组固定清单见CONTEXT.md「板块与主题RS表」（2026-07-15列改版：T-1%/5日%/1月%/盘前/驱动/RS(1日/5日)，价格列已删；XSW同日加回第二组）。务必逐一全量查，不能只抽样几个。**「T-1%」口径是上一个完整交易日的收盘变化，不是盘前——Vic明确说盘前经常是假拉高出货，只有收盘才是真实兑现的**。「盘前（仅供参考）」列只做参考不参与判断板块强弱和排序。RS=对QQQ超额（1日/5日两个口径，选股参考这两个，2026-07-15 Vic定）。row_highlights可选，跟rows等长，值为bull(绿底)/warn(红底)。数据源：report_helpers.sector_rs_rows从cache机械填充。",

  "futures_table": {"headers": ["期货", "点位", "日内变动", "信号"], "rows": [
    ["ES（标普）", "7543.00", "+0.20%", "小幅走高"], ["NQ（纳指）", "29750.25", "+0.66%", "走高"],
    ["YM（道指）", "53169.00", "-0.03%", "基本持平"], ["RTY（罗素）", "3008.00", "-0.21%", "小幅走低"]
  ], "num_cols": [2]},
  "etf_table": {"headers": ["ETF", "价格", "今日%", "进攻线", "谨慎线", "降级线", "50MA", "距50MA%", "判断"], "rows": [
    ["SPY", "748.68", "+0.52%", "748.00", "728.99", "716.49", "-", "-", "盘前摸到进攻线，待收盘确认"],
    ["RSP", "215.20", "+0.14%", "-", "-", "-", "206.64", "+4.15%", "等权跑赢SPY，广度健康"],
    ["QQQ", "721.02", "+1.18%", "726.01", "706.52", "684.14", "705.61", "+2.19%", "谨慎区间内，向进攻线靠拢"],
    ["QQQE", "120.15", "无盘前quote（流动性不足）", "-", "-", "-", "115.39", "+4.13%", "等权ETF暂用上一交易日数据"],
    ["DIA", "527.60", "-0.05%", "-", "-", "-", "505.14", "+4.45%", "延伸最明显"],
    ["IWM", "298.00", "+0.14%", "306.69", "290.00", "285.00", "285.98", "+4.20%", "中性偏强"],
    ["SMH", "607.21", "+2.52%", "-", "-", "-", "572.98", "+5.98%", "盘前大幅反弹"]
  ], "num_cols": [1, 2, 7]},
  "etf_table_note": "指数闸门线（进攻/谨慎/降级）只对SPY/QQQ/IWM三个有意义，其余ETF这三列写\"-\"。50MA距离%全部用Google Sheet真实MA值，不编造。ticker顺序固定为 SPY/RSP/QQQ/QQQE/DIA/IWM/SMH，不要每天顺序不一样。这张表合并了以前分开的\"指数闸门\"和\"大盘ETF技术明细\"两张表（内容完全重复），也替代了01宏观环境里原来的\"A·指数\"50MA延伸表和已删除的5MA偏离度表（Vic没有5MA数据）。",

  "premarket_movers": [
    {"ticker": "KORU", "price": "625.10", "pct": "+15.45%", "pm_vol": "12.4万", "vol_tag": "放量", "catalyst": "Direxion韩国3倍做多ETF，跟随EWY当日+5.4%被3倍放大", "sector_readthrough": "亚洲risk-on情绪", "judgment": "杠杆ETF，波动本身被放大，不代表个股层面机会"},
    {"ticker": "DRAM", "price": "64.90", "pct": "+7.04%", "pm_vol": "3200", "vol_tag": "低量·谨慎", "catalyst": "Roundhill内存主题ETF，跟随SNDK/MU存储链反弹", "sector_readthrough": "存储链风险偏好回升确认", "judgment": "盘前量薄，观察是否延续，不追缺口"}
  ],
  "premarket_movers_note": "扫描范围=LongBridge全量watchlist（约220只）+ reference/ETF_Holdings.csv全部成分股（2026-07-15 Vic扩大，snap_premarket.py自动合并去重，约700只），门槛为|盘前涨跌幅|≥7%才收录，避免大盘正常波动的噪音。百分比一律用preMarketQuote.lastDone相对preMarketQuote.prevClose计算（不是相对两天前的顶层prevClose字段，那个是滞后的）。",
  "_premarket_movers_vol说明": "2026-07-15 Vic要求区分'大量涨'还是'量很低'：pm_vol/vol_tag用report_helpers.pm_volume_cell(pm_cache, ticker)算，来源=snap_premarket.py对每只MOVER单独拉21根日K算出的vol20（20日均量）+vol_ratio_pm=盘前量/vol20。vol_tag：ratio≥20%='放量'（渲染绿badge），<5%='低量·谨慎'（渲染红badge，小单容易打出虚高%，不能同等看待），中间不标注。",
  "_持仓盘前警报说明": "2026-07-15 SYK教训（盘前量大但价没到7%，静默，当天暴跌）：持仓票无条件进snap票池且无条件算量比，|盘前%|≥3或量比≥10%任一触发pos_alert。持仓监控表用report_helpers.position_pm_alert(pm, ticker)把'🔴盘前警报 -3.2%·量比14%'拼进现价列，且该行row_highlights='warn'整行红底（assemble模板已内置）。MOVER全局门槛维持7%（Vic问过要不要调小，结论：SYK的异常在量不在价，降门槛治不了这个病，见CONTEXT.md）。",

  "watchlist_a": [
    {"ticker": "MU", "sector": "半导体", "why": "盘前+8.2% · 量比2.1 · 财报催化", "entry": "125.00", "invalid": "118.50", "target": "132.00", "avoid_if": "SMH跌破20MA"}
  ],
  "watchlist_b_table": {"headers": ["TICKER", "板块", "盘前%", "量比", "待确认条件", "升级触发"], "rows": [], "num_cols": [2, 3]},
  "watchlist_c": ["TICKER — 忽略原因"],
  "watchlist_conclusion": "今日最值得关注：MU（半导体主线延续）",

  "ml_leaders": [
    {"ticker": "MRVL", "price": "82.10", "pct": "+1.2%", "structure": "整理中", "behavior": "2026-07-02 大盘红日跌0.2%跑赢QQQ", "signal": "无setup", "entry": "80.50", "invalid": "77.20"}
  ],

  "defensive_basket": [
    {"ticker": "KO", "price": "82.88", "t1_pct": "-1.50%", "pct": "-0.30%", "role": "超级避险股，今日下跌"}
  ],
  "_defensive_basket说明": "2026-07-21新增t1_pct字段（Vic抓到KO盘前价填错也没显示真实跌幅）：t1_pct=T-1收盘涨跌（唯一保真数字，从cache['metrics'][ticker]['t1_pct']直接取，不能手填猜测）；pct=盘前%，snap_premarket.py快照fresh=0（盘前时段未到/数据stale）时留''空字符串，渲染层会显示'-'不硬填猜测值——宁可空着也不能像KO那次一样填错价格。",
  "old_guard_basket": [
    {"ticker": "WMT", "price": "110.12", "pct": "-1.54%", "role": "价值/股息蓝筹，今日下跌"}
  ],
  "old_guard_note": "老登篮子(BRK.B/SCHD/WMT/WM/MCD/KO/COR)2026-07-06新增，跟超级避险股篮子一起看资金轮动方向。BRK.B目前无法通过LongBridge查询（symbol格式校验bug，跟candlestick接口是同一类问题），暂时只有6只数据。",

  "strong_sector_setups_table": {"headers": ["TICKER", "板块", "Setup标签", "RS(1日/5日)/9EMA/量比", "机器说明", "评分(1-5)"], "rows": [], "num_cols": []},
  "strong_sector_setups_permission": "当日统一仓位/许可提醒（2026-07-15 Vic：仓位/许可每行都一样不占列，放表后一条callout），如：降级档——全表新仓减半、只做A级",
  "_strong_sector_setups说明": "方法2表2026-07-15改版：行序按板块强弱（板块ETF 5日RS降序，watchlist兜底垫底，report_helpers.setup_scan_rows自动排）；看RS(1日/5日)不是RSI；评分(1-5)列=Claude对每行打分（结构质量+板块方向+延伸度+催化共振，5=最高确定性）。",

  "playbook_scenarios": [
    {"title": "情景A — 牛市确认", "trigger": "10Y跌破4.40%且QQQ重返20MA", "action": "分两段增加QQQ/IGV", "target": "QQQ 741.49"},
    {"title": "情景B — 震荡消化", "trigger": "QQQ高开低走前30分钟回吐超50%", "action": "新仓冻结，存量守止损", "target": "等待30分钟量能确认"},
    {"title": "情景C — 转弱防守", "trigger": "10Y突破警戒位或QQQ跌破谨慎线", "action": "高Beta优先减半", "target": "仓位上限按纪律执行"}
  ],
  "positions_moomoo_table": {"headers": ["TICKER", "现价", "成本", "距止损", "持有理由", "失效条件", "论点检查/今日行动"], "rows": [], "num_cols": []},
  "positions_longbridge_table": {"headers": ["TICKER", "现价", "成本", "距止损", "持有理由", "失效条件", "论点检查/今日行动"], "rows": [], "num_cols": []},
  "_positions_longbridge说明": "2026-07-15起LongBridge不再是长持账户（IHI教训，见CONTEXT.md身份与背景），渲染标题='LongBridge账户'，列与Moomoo同一套论点核对口径，无长持豁免。",
  "polymarket_table": {"headers": ["市场问题", "最高概率选项", "概率", "成交量", "交易含义"], "rows": [], "num_cols": [2]},

  "key_takeaways": [
    "期指分化而非全面risk-off：道指偏强、标普持平、Nasdaq受芯片获利回吐拖累",
    "最新市场广度更正面：S&P 500高于20/50MA均达64%以上"
  ],
  "today_position": {
    "primary": ["中性偏多；降低半导体追价，保留金融XLF、等权及医疗XLV"],
    "watch": ["观察10Y与QQQ 20MA 726.01是否同向确认"],
    "avoid": ["避免把弱非农直接等同无条件利多"],
    "invalidate": "若QQQ<-1SD 684.14 → 中性偏多失效，转防守"
  },

  "news_today": ["消息1（来源）", "消息2（来源）"],
  "news_week": ["本周大事1", "本周大事2", "财报：GS/JPM/BAC/WFC/C周二盘前（来自scripts/fetch_earnings_calendar.py，2026-07-15新增，不要偷懒漏查followed universe里谁要报财报）"],
  "industry_radar_table": {"headers": ["活动名称", "日期(SGT)", "主办/主角", "关注重点", "相关标的", "级别"], "rows": [], "num_cols": []},

  "x_sentiment_macro": [
    {"handle": "@KobeissiLetter", "time": "2h", "summary": "美国就业数据14/17个月被下修，累计-710K，就业市场比表面数字弱"}
  ],
  "x_sentiment_stocks": [
    {"handle": "@ohiain", "time": "50m", "ticker": "MU", "note": "Tension & Release setup，缩量回踩后放量", "aligned": "是"}
  ],
  "x_sentiment_note": "2026-07-15新增（Vic要求'加个你的判断和总结'）：紧跟在X观点池帖子列表后渲染的蓝色callout（render_report.py的build_note_callouts()）。不是逐条复述，是把当天所有帖子压缩成Claude的判断——哪几条其实在说同一件事、跟报告里其他信号（市宽/RS/scoreboard）一致还是矛盾、国会交易类没内容就直说。见CONTEXT.md「X观点池」章节末尾说明。",

  "thirteen_dg_rows": [
    {"ticker": "MU", "filer": "Example Capital LP", "form": "13D", "filed_date": "2026-07-03", "note": "主动型，跟Vic的ML Leader名单相关，需留意后续是否有维权/收购动作"}
  ],
  "thirteen_dg_note": "来源：SEC官方atom订阅（type=13D/13G，output=atom），只列与Vic持仓/ML Leader/Watchlist相关的filer，不做全量播报。",

  "squeeze_candidates": [
    {"ticker": "MU", "short_pct_float": "3.2%", "days_to_cover": "1.1", "borrow_fee": "0.25%",
     "short_volume_trend": "平稳，未见加剧", "catalyst": "-", "status": "未触发（远低于20%门槛）"}
  ],
  "squeeze_note": "来源：FINRA做空比例/Days to Cover（双月）+ FINRA每日做空成交量文件 + iborrowdesk借券费率（每日）。只查ML Leader/Watchlist候选/持仓相关标的，不做全市场扫描。",

  "placeholders": {
    "congress_trades": "尚无稳定免费数据源（house/senate stock watcher的S3直链已失效返回AccessDenied；capitoltrades反爬；quiverquant需登录），继续标待接入"
  },

  "footer_sources": "数据来源：LongBridge OpenAPI（实时行情/持仓）、Adanos X Top100、WebSearch（VIX9D/Fear&Greed/宏观）、Polymarket、用户提供（Moomoo CSV/Stockbee截图）。本报告不构成投资建议。"
}
```
