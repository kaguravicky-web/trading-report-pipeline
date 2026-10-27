# xdesk 交接说明（X 盘中简报）

**交接日期**：2026-10-27 · 交给 DS 接手跑，Claude 复查产出。
**本文是给接手人的唯一准绳**。和 `templates/x_intraday_schema.md` 冲突时，以本文为准
（schema 是 8/20 建的，后面 Vic 改过很多次，schema 没跟上）。

---

## 0. 这是什么

Vic 盯 13 个 X 账号，每次他在聊天里打一个字 **`x`**，就跑一轮：
把「上次扫到哪 → 现在」这个窗口里这 13 个号发的帖**一条不漏**地抓下来，
翻成中文一句话摘要，渲染成一个带图的独立网页。

**触发词就是单独一个 `x`**。不要反问「要跑吗」，直接开干。

| | 位置 |
|---|---|
| 脚本 | `D:\交易为生\scripts\`（**这个主库永远不 commit**，见第 9 节） |
| 落盘 | `data/cache/x_intraday_YYYYMMDD.json`（`runs[]` 追加，不覆盖） |
| 产出 | `output/xdesk/YYYY-MM-DD-x.html` + `output/xdesk/index.html` |
| 图 | `output/xdesk/media/YYYYMMDD/`（本地下载，页面点图放大） |
| 名单 | `data/x_accounts.json` ← **单一来源，改名单只改这里** |

跑完在聊天里给一段短的（格式见第 8 节），长的让他去页面看。

---

## 1. 第一步永远是查覆盖，不是开浏览器

```bash
python scripts/x_intraday_merge.py --status
```

它会告诉你窗口起点（＝**上次真的扫到哪**，不是「回溯 2 小时」）和缺口多大，
并且**跨天会自己往前找**。照它给的窗口扫。

**缺口不到 20 分钟就别扫，直接渲染。**

### 跑不跑的判据：缺口里有没有交易时段

Vic 2026-10-10 推翻了「周末不跑」。现在的判据是**缺口里有没有交易时段**：

- 缺口含现金时段（09:30–16:00 ET）→ 必跑
- 只含**周日夜盘**（周日 18:00 ET 开盘之后）→ **也跑**。
  2026-10-26 那轮就是这种：周六周日两天没有现金时段，但有夜盘开盘后 6.3 小时，
  而那 6.3 小时里正好是市场对「特朗普说不打伊朗」的第一次定价——是整轮最值钱的东西。
- 缺口里一点交易时段都没有（纯周日白天）→ 可以跳过，但**要说明理由**。

**他打了 `x` 就是要跑**。判据是用来写进 `notes` 解释覆盖情况的，不是用来拒绝他的。

---

## 2. 账号名单（13 个）

名单只写在 `data/x_accounts.json`。渲染器会拿它核对每一轮的 `accounts_checked`，
**少扫一个号就渲染失败**（这是 2026-09-27 加的闸门，之前名单写在两个地方，必然漂）。

宏观 4 个：`KobeissiLetter` `zerohedge` `NickTimiraos` `unusual_whales`
交易员 9 个：`bluechipdaily` `WalterDeemer` `RichardMoglen` `ohiain` `aleabitoreddit`
`markminervini` `jimcramer` `LeifSoreide` `OliverKell_`

**降权**：`aleabitoreddit`（promoter）和 `jimcramer`（反指）落盘时 `demoted: true`，
卡片降透明度，判断里不给它们权重。**Cramer 的点名不进 `x_watch.json`。**

🔴 **再加人必须 Vic 逐个点头**。不要自己从洪流里捞人。
已删的三个（`spluscollective` `spotgamma` `jasongoepfert`）理由都写在
`data/x_accounts.json` 的 `_removed` 里，**别加回来**。

---

## 3. 采集：必须 search ∪ profile 取并集

这一节是整个交接里最容易出错的地方。**两个来源都在漏，而且漏得静悄悄。**

实测（2026-10-26 那轮，窗口 47 小时）：

```
            search   profile   并集    谁漏了
zerohedge      91       70      93    search 漏 2（它不收回复）
unusual_whales 48       42      56    search 漏 8
RichardMoglen  12        2      12    profile 漏 10
LeifSoreide     7        2       7    profile 漏 5
KobeissiLetter 14       10      14    profile 漏 4
```

**合计 search 漏 10 条、profile 漏 33 条。只用一个来源一定少。**

### 顺序建议：先 search，再对高产号补 profile

**search**（权威、全、不收回复）：

```
https://x.com/search?q=from%3A<HANDLE>%20since_time%3A<EPOCH>%20until_time%3A<EPOCH>&f=live
```

`since_time` / `until_time` 是**秒级 Unix 时间戳**，照 `--status` 给的窗口算。
一个号一个查询，**不要用组合搜索**（2026-07-16 定案：组合搜索会漏帖，宏观组个股组都漏）。

**profile**（补 search 漏掉的回复）：`https://x.com/<HANDLE>`

### 可以直接用的采集函数

X 的 CSP 禁了 `unsafe-eval`，**采集函数必须内联**，不能先定义再调用。
返回**纯数字 id**，不要返回完整 URL —— 完整 URL 会被工具层判成
`[BLOCKED: Base64 encoded data]`。一次最多返回 40 个 id，多了分批取。

search 页用这个：

```js
await new Promise(r=>setTimeout(r,4500));
const acc={};
const h=()=>{document.querySelectorAll('article').forEach(a=>{
  const t=a.querySelector('time[datetime]'); if(!t)return;
  const lk=t.closest('a')?t.closest('a').href:null;
  if(!lk||!/\/status\/\d+/.test(lk))return;
  acc[lk.match(/status\/(\d+)/)[1]]=t.getAttribute('datetime');});};
h(); let last=0,stall=0;
for(let i=0;i<40;i++){
  window.scrollTo(0,document.documentElement.scrollHeight);
  await new Promise(r=>setTimeout(r,1300)); h();
  const n=Object.keys(acc).length; stall=(n===last)?stall+1:0;
  if(i>=3 && stall>=2) break; last=n;}
({n:Object.keys(acc).length, ids:Object.keys(acc).join(' ')})
```

profile 页用这个（要按窗口起点筛）：

```js
await new Promise(r=>setTimeout(r,4000));
const START='<窗口起点 ISO，例如 2026-10-26T03:30:00.000Z>';
const acc={};
const h=()=>{document.querySelectorAll('article').forEach(a=>{
  const t=a.querySelector('time[datetime]'); if(!t)return;
  const lk=t.closest('a')?t.closest('a').href:null; if(!lk)return;
  acc[lk]={utc:t.getAttribute('datetime'),url:lk};});};
h();
for(let i=0;i<40;i++){
  window.scrollTo(0,document.documentElement.scrollHeight);
  await new Promise(r=>setTimeout(r,1300)); h();
  const older=Object.values(acc).filter(x=>x.utc<START).length;
  if(i>=3 && older>=3) break;}           // ← 这两个条件缺一不可，见下面的坑
const all=Object.values(acc);
const inw=all.filter(x=>x.utc>=START).sort((a,b)=>a.utc.localeCompare(b.utc));
({total:all.length, older:all.filter(x=>x.utc<START).length,
  newestAll:all.map(x=>x.utc).sort().slice(-1)[0]||null,
  inWindow:inw.length, ids:inw.map(x=>x.url.match(/status\/(\d+)/)[1]).join(' ')})
```

### 🔴 坑一：置顶推文会让滚动循环第一轮就停

profile 的停止条件如果写成「已收集条目里**最早的**时间 < 窗口起点」，
**置顶推文（可能是几个月前的）会让它在第 1 轮就成立**，当场 break。

2026-10-24 实测：`unusual_whales` 这样只扫到 **2 条**；
改成「**最少滚 4 轮（`i>=3`）＋ 至少 3 条早于起点（`older>=3`）**」之后是 **32 条**。
**差 16 倍，而且不报错。**

### 🔴 坑二（最严重，2026-10-27 刚中）：页面没加载完就采，会静默返回 0 条

停滞判据如果写成「这一轮没新增就停」（`n === last`），**它会把「页面还没渲染」
当成「没有更多结果」** —— 搜索页 4500ms 的等待不够，连续三轮 0==0 直接 break 出 **0 条**。

2026-10-27 实测：**四个号被判零更新，重跑后三个是假的**：

```
RichardMoglen    0 → 4
bluechipdaily    0 → 1
NickTimiraos     0 → 3   ← 名单里标「联储传声筒·不可替代」的那个
```

**NickTimiraos 那 3 条里有一条是联储决议前全轮最值钱的内容**（他逐条列了加息和按住
各三个理由），沉默三天后才发的。**差一点整轮丢掉，而且不会报错。**

修法三件，缺一不可：

1. 停滞 break **必须加 `n > 0`**：`if (i>=3 && stall>=2 && n>0) break;`
2. **首次等待拉到 9000ms**（4500 不够）
3. **滚满 10 轮仍是 0 才当零**：`if (i>=9 && n===0) break;`
   并且把 `arts: document.querySelectorAll('article').length` 一起返回——
   `arts=0` 才是真的空页面。

### 🔴 坑三：profile 时间线每次加载给的不是同一批

同一个号连扫两次，拿到的 id 集合可能只部分重合：
`KobeissiLetter` 两次各 5 条和 8 条、**只重合 3 条**；`bluechipdaily` 一次 6 条一次 2 条。
所以**同一个号多次采集之间也要取并集**，不能用后一次覆盖前一次。

### 🔴 坑四：窗口边界必然和上一轮重叠

窗口起点是「上次最后扫到的那一条」，所以那一条（以及同秒的）会被重复抓到。
**落盘前拿上一轮的 id 集合去重**，否则同一条推会在两天的页面上各出现一次。

### 🔴 坑五：搜索页会把帖子里嵌的旧引用推一起采进来

`document.querySelectorAll('article')` 在搜索页可能命中嵌套的引用推，于是采到
**窗口外的旧 id**。2026-10-27 本轮采到 5 条，其中 **markminervini 两条是广告、
unusual_whales 两条是自家工具推广** —— 正好是最该剔的那类。

修法：**hydrate 之后用精确 `created_at` 再按窗口筛一遍**（hydrate 给的是权威时间）：

```python
A, B = '2026-10-26T03:30:00', '2026-10-27T04:08:59'
run['items'] = [it for it in run['items'] if A <= (it.get('utc') or '')[:19] <= B]
```

### 零条也要核

search 返回 0 **不等于**这个号没发帖。必须用 profile 核它的 `newestAll`：
只有「最新一条的时间 < 窗口起点」才能判定零更新，并写进 `accounts_no_new`。

2026-10-26 那轮四个零更新都是这样核过的：
`bluechipdaily` 10/23 18:44 · `WalterDeemer` 10/24 02:14 ·
`NickTimiraos` 10/22 22:01 · `OliverKell_` 2026-05-13。

---

## 4. 补全正文和图：走 syndication 端点，不用登录

**浏览器那边只负责滚出 id**。正文、图片 URL、精确时间全部交给：

```bash
python scripts/x_hydrate.py --file data/cache/x_intraday_YYYYMMDD.json
```

它对每条推打 `https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=<算出来的>`，
一次拿到三样东西：**全文**（绕开「Show more」截断，比 DOM 的 innerText 还全）、
**图片 URL**、**精确 `created_at`**。结果缓存在 `data/cache/x_tweets.json`，同一条只取一次。

**为什么不在浏览器里抓图**：X 的媒体懒加载，后台标签页 `visibilityState==='hidden'`，
IntersectionObserver 永不触发，`article` 里除头像一张图都没有；
页内 `fetch` 也被 CSP 挡了。

🔴 **一律不截图。** 模型全程不该读任何图像——图是靠 URL 搬出来、Python 下载的，
token 成本就是几个字符串。唯一例外：正文完全为空、结论只在图里，才对那一帖单独 zoom。

🔴 **永远不要登录 X，不要输入任何凭据。** 整条流水线不需要登录。

---

## 5. 组装落盘

读 `templates/x_intraday_schema.md` 拿字段定义。几个必须记住的：

- **`kind` 词表只有这几个**：`macro` / `stock` / `congress` / `cramer` / `13f` / `ep` / `other`。
  别自造。
- **`summary` 必须中文**，一句话：说了什么 ＋ 交易含义（若有）。
- **`utc`** 直接放 hydrate 拿到的 ISO 串，渲染器自己换算 SGT。**别自己算**，算错过。
- **`flag`**：`hot`（要紧，红条）/ `pick`（值得看的 setup，绿条）/ 省略。
- **`demoted`**：`aleabitoreddit` 和 `jimcramer` 置 `true`。
- **`new_to_ledger`**：这个 ticker 今天还没进过 `data/x_watch.json`。
- **`window`** 写人话，例如
  `"10/26 03:30–10/27 03:44 UTC（11:30–11:44 SGT）· 含周一 10/26 完整现金交易日"`。
- **`notes`** 写覆盖情况和异常。抓不到就写明，**不编**。

### 条目顺序：按时间升序，次级键用 status id

2026-10-16 Vic 定的。原来按主题分组，他读一半就会丢掉整块。
**次级键必须用 status id** —— `utc` 只到分钟，同分钟的会并列，排序不稳定。

### takeaway：只写宏观，而且位置在条目之后

2026-10-15 Vic 原话：「**其实我不需要你的 x 总结**，所以总结可以不总结，
或者说在每轮最后才总结宏观」。

- 内容**只写宏观**。交易员那部分已经在条目里，不要在这里重述。
- 位置**在条目之后**。这一条是在渲染层 `render_run()` 收口的，不靠你记得。

---

## 6. 过滤：哪些不进页面

三类，**每一类的理由都要写下来**，不能是「看着不像」：

1. **纯政治 / 文化 / 社会新闻** —— zerohedge 的大头。他一天发 90–100 条，
   真正有盘面含义的大约一半。
2. **广告帖** —— 见下面的闸门。
3. **无正文 / 无市场增量** —— 客套回复、生活照、只有一个链接的帖子。

还有一类要留心：**同一件事的多条**。同一个数字别在页面上出现三遍
（Vic 有「不复述同一个数字」这条规矩），留信息量最大的那条。

### 🔴 排除某批条目的理由本身要核

2026-10-14 踩过：我用一个看似合理的理由排掉一批，**差点漏掉 Kobeissi 全轮最强的两条**。
现在的做法是：剔除清单按理由分组写进脚本，**没判留也没判弃的条目要让脚本报错**，
不能静默漏过。

### 广告帖闸门 PROMO_PAT 和它的半误判

`scripts/render_x_intraday.py` 里的 `PROMO_PAT`，**命中就渲染失败**（Vic 2026-09-25）。

Vic 的原话里有一条判断很准：**晒收益率的帖子最阴——看着像业绩数据，其实是招生广告。**

**2026-10-26 遇到一个半误判，处理方式记下来当范例**：
闸门命中 `@ohiain` 一条，但命中的那个返利码**不在他的正文里，在被他引用的那条推里**——
被引用的是个带返利码、用晒收益写的 prop firm 招生帖，而 ohiain 这条**正是在骂它**。

处理：**不要用 `--allow-promo`**（那会把整轮的闸门关掉，是「QA 把漂移盖章成正确」的典型），
改成**只把引用推正文剥掉、保留他自己的话**。

⚠ 剥的时候注意：**替换文字里别把广告的数字和话术又写回去**。
我第一次写的剥除说明里带了那个广告的金额，等于把广告搬上了页面，返工了一次。

---

## 7. 四道会让渲染失败的闸门

```bash
python scripts/render_x_intraday.py --date YYYY-MM-DD
```

| 闸门 | 触发 | 逃生口 |
|---|---|---|
| 落盘文件不存在 | 没有 `data/cache/x_intraday_*.json` | 先扫描落盘 |
| **名单缺口** | 某轮 `accounts_checked` 少于 `data/x_accounts.json` | `--allow-roster-gap`（确实不打算扫全时才用） |
| **广告帖** | `PROMO_PAT` 命中 | `--allow-promo`（**几乎永远不该用**，见第 6 节） |
| 图片下载 | 网络问题 | `--no-media`（只引远端 URL，不下载） |

逃生口是给真有理由的情况留的。**用之前先想清楚是不是在把问题盖过去。**

---

## 8. 按号对条数要做两次

Vic 2026-10-15 定的。**采集后一次、组装后一次**，而且第二次要**拿渲染出来的页面对**，
不是对数据文件（数据文件对自己永远一致，对不出渲染层的问题）。

```python
import io, json, re
from collections import Counter
h = io.open(r'output\xdesk\2026-10-26-x.html', encoding='utf-8').read()
d = json.loads(io.open(r'data\cache\x_intraday_20261026.json', encoding='utf-8').read())
page = Counter(re.findall(r'class="who"[^>]*>(@[A-Za-z0-9_]+)', h))
data = Counter(x['handle'] for x in d['runs'][0]['items'])
for k in sorted(set(page) | set(data)):
    print(k, data[k], page[k], '' if page[k] == data[k] else '不一致')
```

### 聊天里给的简报格式

```
X盘中 · 第N轮 · 窗口 13:10–15:25 SGT · 12条（3🔴）
🔴 <一句话，最要紧的那条>
· <个股条目：@号 $TICKER 一句话>
· <宏观条目：@号 一句话>
→ output/xdesk/YYYY-MM-DD-x.html（含 N 张图）
```

只列 `flag` 非空的 ＋ 个股类；宏观类没有 flag 的折成一行数量，**不刷屏**。

---

## 9. 硬规矩

1. 🔴 **永远不登录 X，不输入任何凭据。** 整条流水线不需要。
2. 🔴 **一律不截图。** 见第 4 节。
3. 🔴 **主库 `D:\交易为生` 永远不 commit。** 它含 `data/tradebook.json`、
   `data/x_watch.json` 和券商凭据路径。本仓库是人工挑选的镜像，不是它的 remote。
4. 🔴 **`output/` 是另一个独立的公开仓库**（`kaguravicky-web/trading-reports`），
   走 `python scripts/publish.py` 推送，而且**只在 Vic 开口时推**。
   `tradebook.html` 从来不上传。
5. 补丁脚本**只用写文件的工具生成**，不要用 shell heredoc —— 转义会被搞坏，
   而且 heredoc 里的中文在 Windows 控制台会乱码。
6. 这个脚本会原地把 `items` 换成过滤后的结果，所以**填充脚本要加一道
   `assert len(items) == <原始条数>`** —— 对已过滤的文件再跑一遍会按错的索引二次过滤。
   2026-10-24 踩过：201 → 93 → 39，而且不报错。

---

## 10. Vic 拍过的板（按日期，别推翻）

| 日期 | 决定 |
|---|---|
| 2026-07-16 | 一个号一个查询，**不用组合搜索**（会漏帖） |
| 2026-09-25 | **广告帖过滤掉**，闸门命中就渲染失败 |
| 2026-09-27 | 名单单一来源 `data/x_accounts.json`，少扫一个渲染失败 |
| 2026-10-10 | **周末也跑**，判据改成「缺口里有没有交易时段」 |
| 2026-10-13 | **profile ∪ search 取并集**；停止条件要最少滚 4 轮 |
| 2026-10-14 | 排除某批条目的**理由本身要核**；Cramer 的点名不进 `x_watch` |
| 2026-10-15 | 「我不需要你的 x 总结」→ takeaway 移到条目之后、**只写宏观**；名单 15→13 |
| 2026-10-16 | 条目**按时间升序**，次级键用 status id |

---

## 11. 一轮的完整命令序列

```bash
cd /d/交易为生

# ① 查覆盖（永远是第一步）
python scripts/x_intraday_merge.py --status

# ② 导入当天盘前扫描（如果有）
python scripts/x_intraday_merge.py          # 当天重跑过加 --redo

# ③ 浏览器采集：13 个号逐个 search，高产号补 profile，取并集
#    零条的号用 profile 核 newestAll，确认后进 accounts_no_new
#    和上一轮的 id 去重

# ④ 骨架落盘（runs[] 追加），然后补全正文/图/精确时间
python scripts/x_hydrate.py --file data/cache/x_intraday_YYYYMMDD.json

# ⑤ 读补全后的正文，填 kind / ticker / summary / flag，剔除三类，按时间升序排
#    （填充脚本记得加 assert len(items) == 原始条数）

# ⑥ 渲染
python scripts/render_x_intraday.py --date YYYY-MM-DD

# ⑦ 按号对条数（第二次，拿页面对），然后在聊天里给简报
```

---

## 12. 交接时的待办

- **今天（2026-10-27）这轮还没跑**，缺口起点是 **10/26 03:30 UTC**，
  里面含**周一 10/26 完整现金交易日**。这是接手后的第一个活。
- 本仓库里 **3 个文件已在本次交接中更新到当前版本**：
  `scripts/render_x_intraday.py`（490 → 628 行，补上 9/27 名单闸门、
  10/15 takeaway 移到条目之后、10/16 条目升序）、
  `scripts/x_intraday_merge.py`（342 → 373 行）、`templates/x_intraday_schema.md`。
  `scripts/x_hydrate.py` **本来就是最新的，没改**（它从 8/20 建好之后没再动过）。
- **`data/x_accounts.json` 本次新增进仓库** —— 名单闸门要读它，之前仓库里没有，
  拉下来直接跑不起来。
- ⚠ 本仓库是 **public**，而 `data/tradebook.json`（190 条真实交易记录）和
  `data/x_watch.json` 自 2026-08-21 起就在里面。Vic 已知情，**本次交接不动它们**
  （`x_watch.json` 是 xdesk 要喂的台账，接手人用得上）。
  **不要再往里加任何新的持仓或凭据类文件。**
