# 板块扫描降级方案（当东方财富API被封时）

## 问题背景

`push2.eastmoney.com` 的板块排行API经常被IP封锁，返回空响应。此文档记录降级方案。

## 方案一：财联社电报（推荐）— 浏览器JS提取法

**URL:** `https://cls.cn/telegraph`

**特点:**
- CLS页面底部有**实时板块排名widget**（行业板块+概念板块+个股涨幅榜），开盘即更新
- 无需等待午评（11:30-12:00），10:00 AM即可提取
- 比逐条滚动快得多

### 方法A：browser_console JS提取（推荐，更快）

当push2被全面封锁时（行业+概念双API均返回空）：

```javascript
// Step 1: 浏览器导航到 cls.cn/telegraph

// Step 2: 用不同范围的substring尝试提取板块rankings
document.body.innerText.substring(5000, 15000)  
// 调整范围找到包含下面内容的段落：
//   "行业板块 概念板块 地域板块"
//   "板块名称 涨跌幅 资金流入"
//   "小金属 +3.02% 2703.18万"
//   "个股涨幅榜 个股跌幅榜"
//   "股票名称 涨跌幅 涨跌价"

// Step 3: 从提取的文本中直接读取：
//   行业板块排名（板块名+涨跌幅+资金流入）
//   概念板块排名（更精细的主题映射）
//   个股涨幅榜（含非688可买标的的涨幅）
//   实时指数（底部列表）

// Step 4: 用 qt.gtimg.cn 批量查候选股实时行情
// Step 5: 用 web.ifzq.gtimg.cn 拉60日K线算分位
```

**优势：**
- 一次调用提取全部板块排名+个股涨幅榜+指数
- 不需要反复scroll加载
- 数据是实时排名（不是12:00的午评总结）

**注意：**
- CLS页面重构时 substring 范围需微调
- 个股涨幅榜中的688标的需要手动过滤
- 如果第一次提取返回空字符串，尝试滚动一次后重试

### 方法B：午评提取法（备用，仅11:30-12:00后可用）

**典型内容格式：**
```
午评：创业板指半日跌近1% AI应用端、煤炭板块集体爆发
...盘面上，AI应用端爆发，XX涨停...
煤炭板块走强，XX涨停...
下跌方面，CPO概念走弱...
```

**提取流程：**
1. 浏览器导航到 `cls.cn/telegraph`
2. 搜索「午评」关键词（通常在11:30-12:00之间发布）
3. 从午评文本中提取：今日强势板块、涨幅居前个股、弱势板块
4. 注意：CLS内容是滚动更新的，需要用 `browser_scroll(direction='down')` 加载更多

## 方案二：腾讯个股批量查询推断板块强弱

如果你已经知道要查的板块成分股代码，可以直接批量拉取它们来判断板块强弱：

```bash
# 煤炭板块龙头批量查询
curl -s "https://qt.gtimg.cn/q=sh600188,sh601225,sh600985,sh600403,sh601699" | python3 -c "
import sys, re
raw = sys.stdin.buffer.read()
text = raw.decode('gbk', errors='replace')
for line in text.strip().split(';'):
    ...
"
```

从个股涨跌幅可以反向推断板块强度。

## 方案三：腾讯板块指数

已知的部分腾讯板块指数代码（格式 `zsBKXXXX`）：
- 煤炭 `zsBK0459`
- 新能源 `zsBK0503`
- 医疗 `zsBK0488`
- 半导体 `zsBK0536`

但此API(`qt.gtimg.cn/q=zsBKXXXX`) 经常返回 `v_pv_none_match="1"`，可靠性存疑。

## 已知稳定的API列表

| 用途 | API | 编码 | 说明 |
|:----|:----|:----|:-----|
| 个股实时行情 | `qt.gtimg.cn/q=sh{code}` 或 `sz{code}` | GBK | ✅ 最稳定 |
| 指数行情 | `qt.gtimg.cn/q=sh000001,sz399001,...` | GBK | ✅ 同上 |
| 日K线 | `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,30,qfq` | UTF-8 | ✅ 稳定 |
| 板块排行 | `push2.eastmoney.com/api/qt/clist/get?...fs=m:90+t:2...` | UTF-8 | ⚠️ 常被封 |
| 概念板块 | `push2.eastmoney.com/api/qt/clist/get?...fs=m:90+t:3...` | UTF-8 | ⚠️ 常被封 |
| 行业资金流 | `data.eastmoney.com/bkzj/hy.html` | — | JS渲染，难抓取 |
