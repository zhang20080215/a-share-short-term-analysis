# 新浪财经日内分时数据API（5分钟K线）

## 1. API端点

```
GET http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale={minutes}&datalen={count}
```

| 参数 | 必填 | 说明 | 示例 |
|:----|:----:|:----|:----|
| `symbol` | ✅ | 股票代码：`sh600584`(沪) / `sz000021`(深) | `sh600584` |
| `scale` | ✅ | 分钟周期：`5`(5分) / `15`(15分) / `30`(30分) / `60`(60分) | `5` |
| `datalen` | ⚠️ 建议 | 返回的K线数量上限（约等于最近N个该周期的数据点） | `120` |

**注意：** 用 `http://` 而非 `https://` — HTTPS在某些环境下可能被302重定向。

## 2. 返回格式

```json
[
  {
    "day": "2026-06-29 09:35:00",
    "open": "103.000",
    "high": "105.800",
    "low": "102.990",
    "close": "103.690",
    "volume": "25096156",
    "ma_price5": 103.690,
    "ma_volume5": 25096156,
    "ma_price10": 103.690,
    "ma_volume10": 25096156,
    "ma_price30": 103.690,
    "ma_volume30": 25096156
  },
  ...
]
```

字段说明：
- `day`: 该5分钟区间的结束时间戳（如 `09:35:00` 表示09:30~09:35这5分钟）
- `open/high/low/close`: 该区间的OHLC价格（字符串）
- `volume`: 该区间的成交量（股数），整数
- `ma_price5/ma_volume5`等: 该区间计算的移动平均（历史数据的递推均线，作为参考）

## 3. 典型用法

### 3.1 筛选今日数据

```python
import json, urllib.request

url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600584&scale=5&datalen=120"
resp = urllib.request.urlopen(url, timeout=8).read().decode('utf-8')
data = json.loads(resp)

# 筛选今日的数据点
today = "2026-06-29"
today_points = [p for p in data if p['day'].startswith(today)]

print(f"今日共{len(today_points)}个5分钟点")
```

### 3.2 核心分析指标

```python
opens = [p for p in today_points if '09:3' in p['day'] or '09:4' in p['day']]
print(f"早盘(09:30-09:45): O={opens[0]['open']}→C={opens[-1]['close']}")

all_high = max(float(p['high']) for p in today_points)
all_low = min(float(p['low']) for p in today_points)
all_open = float(today_points[0]['open'])
all_close = float(today_points[-1]['close'])

print(f"全天: O={all_open} H={all_high} L={all_low} C={all_close}")
print(f"日内V反幅度: (C-L)/L×100 = {(all_close-all_low)/all_low*100:.1f}%")
print(f"高点到低点跌幅: (H-L)/H×100 = {(all_high-all_low)/all_high*100:.1f}%")
```

### 3.3 关键时点定位

```python
# 找到日内最低点和最高点的发生时间
min_point = min(today_points, key=lambda p: float(p['low']))
max_point = max(today_points, key=lambda p: float(p['high']))
print(f"日内最低: {min_point['day'].split()[1]} @{min_point['low']} 量{int(min_point['volume'])/10000:.0f}万")
print(f"日内最高: {max_point['day'].split()[1]} @{max_point['high']} 量{int(max_point['volume'])/10000:.0f}万")
```

## 4. 五步诊断法（实战用途）

当用户问「XX今天分时怎么走」或你想判断「这个标的今天能不能进」时：

```
Step 1: 先拉O/H/L/C四个值 → 初判蜡烛形态
Step 2: 再拉5分钟K线 → 确认V反质量
  - 从最低点到当前价反弹了超过5%？→ 抄底盘已入场，底部大概率确认
  - 反弹<2%且缩量？→ 可能在下跌中继，不进场
Step 3: 检查10:00-10:40的恐慌砸盘段
  - 放量砸盘后缩量企稳？→ 空头力量释放完毕
  - 持续放量下跌？→ 还有进一步下跌空间
Step 4: 对比早盘和午后走势
  - 午后比午间收盘高？→ 资金在回流
  - 午后创新低？→ 趋势继续恶化
Step 5: 判断进场时机
  - 距最低点已反弹>5% → 错过最佳买点，等回调再考虑
  - 距最低点反弹2-5% → 仍在底部区域，可以考虑
  - 还在最低点附近 → 可能是下跌中继，等确认
```

## 5. 与腾讯实时行情四值(O/H/L/C)的关系

| 维度 | 腾讯实时行情(1个点) | 新浪5分钟K线(多个点) |
|:----|:-----------------:|:------------------:|
| 数据量 | 1个O/H/L/C | 最多120个O/H/L/C |
| O/H/L/C精度 | 是一样的（同一数据源） | ✅ 能看到走势路径 |
| 能否知道V反时间 | ❌ 不能 | ✅ 精确到5分钟 |
| 能否计算每个时段成交量 | ❌ 不能 | ✅ 可以 |
| 能否定位最低/最高发生时刻 | ❌ 不能 | ✅ 精确到5分钟 |

**何时用腾讯（快）：** 常规蜡烛检查（上影线占比判断），1个curl搞定
**何时用新浪（全）：** 用户要求看分时/确认V反/追高判断/日内走势分析

## 6. 已知限制

- **每日数据量有限：** 5分钟K线一天约48个数据点（4小时×12个/小时）。`datalen=120` 返回约2.5天数据
- **最小周期为5分钟：** 不支持1分钟级别K线
- **HTTP非HTTPS：** HTTPS可能被重定向到301，使用 `http://`
- **数据时效：** 返回最近N个5分钟K线，收盘后数据保持不变
- **期货/ETF/指数也支持：** `symbol=sh000001`（上证指数）、`symbol=sz159636`（ETF）
  - 期货格式：`symbol=sfCU2409`（沪铜期货）
