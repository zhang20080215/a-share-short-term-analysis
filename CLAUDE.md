# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这个仓库是什么

**不是软件项目，是一套 Claude Skill（提示词框架）**，名为 `a-share-short-term-analysis`，用于 A 股短线选股/盯盘/持仓分析。
交付物 = Markdown 方法论 + 一组独立 Python 工具脚本。**没有构建、没有 lint、没有测试框架**，不要去找 package.json / Makefile / pytest。

改动的正确形态是：**改 Markdown 规则**，或**改/加 templates/ 下的单文件脚本**。

## 三处副本 —— 改完必须同步，否则不生效

| 路径 | 角色 |
|:---|:---|
| `D:\AutoAgent\a-share-short-term-analysis` | **源仓库**（本目录，git，origin = github.com/zhang20080215/a-share-short-term-analysis） |
| `C:\Users\zhang\.claude\skills\a-share-short-term-analysis` | **Claude Code 实际加载的已装副本** |
| `~/.hermes/skills/software-development/a-share-short-term-analysis/` | Hermes 运行时副本（见 `references/github-sync.md`） |

**纪律：改源仓库后必须 cp 到 `~/.claude/skills/` 已装目录，改动才对后续会话生效。** 只改源仓库 = 白改。

```bash
cp -r references templates SKILL.md "C:/Users/zhang/.claude/skills/a-share-short-term-analysis/"
```

**是否 push 到 GitHub 由用户逐次决定**（不要自动推）。仓库是 **public**，凭据严禁入库。
fine-grained PAT 默认无写权限导致 403 的排查过程见 `references/github-sync.md`。

## Python 环境（本机 Windows，有坑）

```bash
PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/atr-stop.py
```

两条都是必需的：

- **必须写绝对路径。** PATH 上的 `python` 是微软商店应用执行别名空壳（`WindowsApps\python.exe`，版本 `0.0.0.0`，执行返回 exit 9009）。`command -v python` / `Get-Command python` 会找到它 → **假阳性**。探测 Python 必须实跑 `-V` 并检查退出码，不能只看 `command -v`。真实 conda base 在 `D:\Anaconda`（3.11.5，含 pandas/requests），环境清单见 `~/.conda/environments.txt`。
- **必须带 `PYTHONIOENCODING=utf-8`。** 控制台默认 GBK，脚本里的 emoji（✅/🚀）会抛 `UnicodeEncodeError` 让脚本**中途崩掉**，不只是乱码。

⚠️ **`references/api-patterns.md` 开头描述的 `/usr/bin/python3.12` + akshare 是 Hermes（Linux）环境，不适用本机。** 本机没有 akshare，脚本一律只用标准库 + HTTP 直连行情 API。

## 常用命令

没有测试框架。改完脚本的验证方式就是编译 + 实跑：

```bash
"D:/Anaconda/python.exe" -m py_compile templates/*.py
```

各脚本用法（均可直接跑，无参数时走内置 DEMO/SAMPLE）：

```bash
PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/cost-calc.py 2.27 2.30 2000
```

- `atr-stop.py` — 拉 60 日 K 线算 ATR(14) → 建议止损 + 按风险预算反推股数（改文件头部 `ACCOUNT`/`RISK_PCT`/`STOCKS` 配置）
- `cost-calc.py` — 佣金/印花税/过户费净盈亏，判断做 T 是否值得
- `emotion-temp.py` — 情绪温度分（0-100）→ 周期阶段 → 自动选模式与仓位水位
- `picks-ledger.py` — 选股台账 `picks.jsonl`：`add` / `close --id X --exit Y` / `report --by setup|emotion_phase|mode|sector`
- `portfolio-ledger.py` / `lhb-fetch.py` / `closing-check.py` — 持仓账本 / 龙虎榜拉取 / 收盘检查

**⚡ 全局选股的第一条命令（2026-09-01 新增，别再逐个手搓脚本）：**

```bash
PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/a-scan.py     # A股，2.8s
PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/hk-scan.py    # 港股，2.8s
```

一条命令出齐六步法数据：大盘+涨跌家数 / 情绪温度自动合成（复用 emotion-temp.py）/ Step2a 连板梯队 / Step2b 涨停归类 / 行业+概念板块排行 / 28行业铺面（锚定位vs弹性位）/ 候选自动过闸（60日分位·上影·涨幅区间·均线·ATR止损）。快照落 `scans/scan-{a,hk}-YYYYmmdd-HHMM.json`（已 gitignore）。

> **为什么必须先跑它：** 2026-09-01 复盘——一次港股全局选股被拆成 **15 次**工具调用、耗时十几分钟，结论出来时数据已过时。实测真正的网络 IO **不到 3 秒**，95% 的时间花在工具往返上。合并成单脚本后 2.8 秒。只对脚本没覆盖的部分补拉（催化新闻/龙虎榜/分时），**不要重复拉它已经给了的数据**。

## 架构

### SKILL.md（3600+ 行，唯一加载入口）
顺序是：`何时使用` → **`📚 参考文件` 索引表** → `六步法`（STEP1宏观→STEP2板块→STEP3个股→STEP4基本面→STEP5买卖→STEP6复盘）→ 各场景章节（做T / 长线底仓高抛低吸 / 全市场扫描 / 板块归因 / 换仓评估）→ `Critical Safety Checks`。

注意：文件里混着三类内容——**方法论**、**输出模板**（`## 推荐：XXX（评级X⭐）` 这类给 Claude 照抄的回复骨架）、以及**历史案例残留**（`## 中天科技：❌ 今天窗口已经过了` 这类某天某票的文字）。第三类是技术债，见下方治理规范的迁移 backlog。

### references/ —— 靠文件名区分两类
- **中文文件名 = 可复用原则/方法论**（`资金管理体系.md`、`止盈体系.md`、`情绪周期与自动模式路由.md`、`量价背离体系.md`…）
- **`YYYYMMDD-英文-slug.md` = 单日单票案例复盘**（`20260703-gold-fade-case.md`…）

必读的硬规则集中在 `session-pitfalls.md`（铁律3-9）与 `扫描全覆盖.md`（STEP3 必须覆盖 24 个行业板块，不得因"之前没讨论过"跳过）。

⚠️ 命名易混：`*-divergence.md` 案例讲的是**个股走势分歧**（A涨B跌归因），与 `量价背离体系.md` 的**量价背离**不是一个概念。

### templates/ 
7 个互相独立的单文件脚本，无包结构、无 `requirements.txt`。与 references 一一配套（如 `atr-stop.py` ↔ `资金管理体系.md`）。

### 数据源
- **主力：腾讯**——实时 `qt.gtimg.cn/q=<codes>`（**GBK 编码，需转 UTF-8**；`~` 分隔字段），日 K `web.ifzq.gtimg.cn/.../fqkline/get`（**字段顺序是 日期,O,C,H,L,V——不是 OHLCV**，需 User-Agent）
- **东方财富——必须按域名区分，2026-09-01 实测更正**（旧结论"push2 系列不可作主力、板块排行要走 CLS 浏览器"是把主域的封锁错误外推到了整个东财）：

| 域名 | 状态 | 用途 |
|:---|:---:|:---|
| `push2delay.eastmoney.com` | ✅ **0.11s** | 行业板块 `m:90+t:2` / 概念板块 `m:90+t:3` / 板块资金流 `fid=f62` / 全A榜(5555只) —— **全部可用，可作主力** |
| `push2ex.eastmoney.com` | ✅ 0.25s | `getTopicZTPool` 涨停池 / `ZBPool` 炸板池 / `DTPool` 跌停池。涨停池自带 `hybk`(行业)+`lbc`(连板)+`ltsz`(流通市值)+`zbc`(炸板)，**一个请求同时满足 Step2a 与 Step2b** |
| `push2.eastmoney.com` | ❌ | clist 被本机 IP 封（stock/get 时通时断）—— 不要依赖 |
| `hq.sinajs.cn` | ❌ | 403，需 Referer |

  **CLS 电报已降级为催化/新闻验证专用，不再是板块排行的必经路径。**板块排名 API 真失败时才走降级链（ETF排名 → 个股铺面扫描 → CLS电报验证）。以上三源已内置进 `a-scan.py`，任一源失败自动跳过不阻塞。

- **腾讯批量上限：单请求 250 只 / 0.22s。**不要 25 只一批还加 `sleep`——那是自己给自己上锁。K线用并发（12 只串行 3.7s vs 并发 1.1s）。

## 改这个框架的规矩

来自 SKILL.md「🧹 框架治理规范」——框架已 3600+ 行，规则膨胀有过拟合与自相矛盾风险：

1. **`[原则]` 进主文件，`[案例]` 沉 references。** 耐用规则（板块优先、ATR止损）留 SKILL.md；单日单票观察写成 references 案例文件，主文件只留一句索引。不要把复盘长文塞进 SKILL.md。
2. **加新规则前先查重**，发现矛盾先调和（如"不做正T" vs 高抛低吸已调和过）。
3. **新增 reference 要挂两处**：`📚 参考文件` 索引表加一行，**并且**在对应流程步骤（如六步法铁律区）加一行指针。只挂索引表往往不会被真正读到。
4. 每次改动顺手迁移 1-2 条 backlog 案例，不必一次性重构。

## 给用户建议的边界

可以给客观分析与决断性判断，但**不替用户下达"买X股/仓位X%/止损X元"的个人交易执行指令**——那步决策留给用户本人。
