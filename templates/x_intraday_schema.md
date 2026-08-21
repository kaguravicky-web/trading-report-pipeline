# X 盘中简报（xdesk）· 扫描规程 + 数据格式

2026-08-20 建。Vic：「我的盘前盘后报告的 x 台账，我想做成当天内可以随时翻阅、1-2 小时的
单独总结，聊天窗口也可以，但是要抓的多一点，希望能看到图」。

跟盘前那次 X 扫描（`data/cache/x_scan_YYYYMMDD.json`，一天一次、覆盖近一周、进报告 callout）
是**两个东西**，互不覆盖：

| | 盘前 X 观点池 | X 盘中简报 xdesk |
|---|---|---|
| 频次 | 一天一次，盘前流程内 | **Vic 喊「x」才跑**，一天可跑 N 轮 |
| 窗口 | 近一周 | **距上一轮到现在**（当天第一轮回溯 2 小时） |
| 落盘 | `x_scan_YYYYMMDD.json` | `x_intraday_YYYYMMDD.json`（`runs[]` 追加） |
| 产物 | 报告里的一节 | 独立页 `output/xdesk/YYYY-MM-DD-x.html` |
| 图 | 无 | **有**，帖子里的图下载到本地显示 |
| 深度 | 每号扫到近期为止 | **每号翻到窗口起点为止，一条不漏**，含回复/引用推 |

---

## 0. 先查覆盖，别急着开浏览器

Vic 2026-08-20：「如果我跑过盘前盘后，时间上有重复的，你就不用重复跑，看时间戳，
直接拿了加入这个页面」。

```bash
python scripts/x_intraday_merge.py --status   # 覆盖到哪了、缺口多大
python scripts/x_intraday_merge.py            # 导入盘前扫描（当天重跑过就加 --redo）
```

浏览器**只扫「最后覆盖点 → 现在」**。缺口不到 20 分钟就别扫，直接渲染。
导入的条目没有 tweet 链接所以没有图——等盘前扫描开始记 `url` 就有了。

## 1. 账号池

盘前那 13 个照搬（`x_scan_*.json` 的 `accounts_scanned`）：

```
KobeissiLetter  zerohedge  spotgamma  NickTimiraos  bluechipdaily  WalterDeemer
RichardMoglen  ohiain  spluscollective  aleabitoreddit  BillAckman  unusual_whales  jimcramer
```

**2026-08-20 Vic 圈定新增 2 个**（xdesk 专用，暂不改盘前那份名单）：

```
markminervini    # Stage/领导股，跟 Vic 的框架同源，常配图
jasongoepfert    # SentimenTrader，统计型情绪/广度信号
```

→ **xdesk 账号池 = 15 个**。

🔴 **再扩充必须 Vic 逐个点头才进池**（`feedback_scan_roster_not_firehose`：名单先定死，
不在洪流里捞人）。8/20 提过但**他没圈、所以不扫**的：@DeItaone、@FirstSquawk、
@charliebilello、@Barchart。

**低产账号观察中（没他发话不要自己剔）**：@bluechipdaily（最近一条真正的标的评论停在 8/12）、
@BillAckman（本周全是政策评论/转发）、@unusual_whales（国会/期权异动整周 0 条）。
每轮扫到就记进 `accounts_no_new`，攒够几轮再拿数据找他定去留。

**降权标记**：`aleabitoreddit` = promoter，`jimcramer` = 反指——渲染时 `demoted: true`
（卡片降透明度），判断段落里不给它们权重。

## 2. 窗口规则

- 起点一律是「**上一次真的扫到哪**」，不是固定 2 小时。`--status` 会算给你，
  **跨天也会往前找**（2026-08-21 修）——早上第一次跑时，起点是昨天最后扫到的时刻，
  中间常常隔着一整个美股交易日；按「回溯 2 小时」扫会把昨晚盘中全漏掉，而且漏得静悄悄。
- 只有真的一次都没扫过（往前找 3 天都空）才回溯 2 小时。
- 判断「这条要不要」只看 `<time datetime>` 的 UTC 时间戳，**不看 X 显示的相对时间**
  （「2h」这种在滚动时会变）。
- 落盘时 `window` 字段写人话，例如 `"8/20 05:10–07:25 UTC（13:10–15:25 SGT）"`。

## 3. 抓取方法（照 CONTEXT.md「X 观点池」的既有规矩，只加图这一项）

- 逐个账号单独查 `https://x.com/search?q=from%3A账号名&f=live`。**不用组合搜索**
  （2026-07-16 定案：组合搜索会漏帖，宏观组个股组都漏）。
- 滚动用 `computer.scroll` 真实触发 X 的虚拟列表；`window.scrollBy` 在部分账号页无效。
- 取正文用 `javascript_tool` 读 `<article>`，**不用 `get_page_text`**
  （2026-07-20：它只抓 DOM 里第一个 `<article>`，滚动后不更新，会读到假内容）。
- 🔴 **一律不截图**。图不是靠截图拿的，是靠下面这段 JS 把 `pbs.twimg.com` 的 URL
  搬出来，渲染器再用 Python 下载——**模型全程没有读过任何图像**，token 成本就是几个 URL 字符串。
  唯一例外仍照旧：正文完全为空、结论只在图里，才对那一帖单独 zoom。

**一次性提取（每个账号页滚动到位后跑一次，返回结构化 JSON）：**

```js
Array.from(document.querySelectorAll('article')).map(a => {
  const t = a.querySelector('time');
  const link = t && t.closest('a') ? t.closest('a').href : null;
  const txtNodes = a.querySelectorAll('[data-testid="tweetText"]');
  const media = Array.from(a.querySelectorAll('img'))
    .map(i => i.src)
    .filter(s => s.includes('pbs.twimg.com')
              && !s.includes('profile_images') && !s.includes('/emoji/'));
  return {
    utc: t ? t.getAttribute('datetime') : null,   // ISO UTC，唯一可信的时间源
    url: link,
    text: txtNodes[0] ? txtNodes[0].innerText : '',
    quoted: txtNodes[1] ? txtNodes[1].innerText : '',   // 引用推的正文
    media: media
  };
}).filter(x => x.utc)
```

`innerText` 能绕开 X 的「Show more」截断，比 `read_page` 拿到的正文更完整。

## 4. 落盘格式 `data/cache/x_intraday_YYYYMMDD.json`

**追加，不覆盖**：文件已存在就读出来往 `runs[]` 里 append 一个新对象。

```json
{
  "date": "2026-08-20",
  "runs": [
    {
      "run_id": 1,
      "run_at": "2026-08-20T15:25+08:00",
      "window": "8/20 05:10–07:25 UTC（13:10–15:25 SGT）",
      "accounts_checked": ["KobeissiLetter", "..."],
      "accounts_no_new": ["NickTimiraos", "..."],
      "items": [
        {
          "handle": "@spluscollective",
          "utc": "2026-08-20T07:11:00.000Z",
          "kind": "stock",
          "ticker": "ADI",
          "summary": "中文一句话：说了什么 + 交易含义（若有）",
          "url": "https://x.com/spluscollective/status/...",
          "media": ["https://pbs.twimg.com/media/xxx?format=jpg&name=small"],
          "flag": "hot",
          "demoted": false,
          "new_to_ledger": true
        }
      ],
      "takeaway": "本轮一段判断（见下）",
      "notes": "覆盖情况/异常说明，抓不到就写明，不编",
      "cost_log": [{"account": "KobeissiLetter", "tool_calls": 4, "approx_chars": 3000}]
    }
  ]
}
```

字段说明：

- `kind`：`macro` / `stock` / `congress` / `cramer` / `13f` / `other`——决定卡片颜色和筛选。
- `utc`：直接放 JS 拿到的 ISO 串，渲染器自己换算 SGT。别自己算，算错过一次。
- `summary`：**中文**。子代理返回英文的话落盘前翻掉（老毛病，QA 第 5 条抓的就是这个）。
- `media`：URL 数组，原样搬，别改尺寸参数——渲染器会统一改成 `name=medium`。
- `flag`：`hot`（🔴 要紧，卡片左边红条）/ `pick`（🎯 值得看的 setup，绿条）/ 省略。
- `demoted`：promoter / 反指账号置 true。
- `new_to_ledger`：这个 ticker 今天还没进过 `data/x_watch.json`——提示可以补台账。
- `takeaway`：**必写**。不是复述帖子，是把这一轮压成 1-2 句：谁跟谁在说同一件事
  （共振=信号，孤例=噪音）、跟当天报告的主线是否一致，不一致就明说。没料就写「本轮无实质增量」。

## 5. 渲染

```bash
python scripts/render_x_intraday.py
```

产出 `output/xdesk/YYYY-MM-DD-x.html`（当天全部轮次，最新在上）+ `output/xdesk/index.html`。
图下到 `output/xdesk/media/YYYYMMDD/`，页面点图放大。`--no-media` 跳过下载只引远端 URL。

## 6. 聊天窗口简报格式

渲染完在聊天里给一段短的，长的去页面看：

```
X盘中 · 第N轮 · 窗口 13:10–15:25 SGT · 12条（3🔴）
🔴 <一句话，最要紧的那条>
· <个股条目：@号 $TICKER 一句话>
· <宏观条目：@号 一句话>
本轮判断：<takeaway>
→ output/xdesk/2026-08-20-x.html（含 4 张图）
```

聊天里只列 `flag` 非空的 + 个股类，宏观类没有 flag 的折成一行数量，不刷屏。
