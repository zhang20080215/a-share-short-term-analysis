# LOF/ETF 基金分析指南

## 何时使用
用户问到一个LOF（上市型开放式基金）或ETF代码时（如160644, 159636），需要区分：这是基金，不是个股。分析方法不同。

## ⚠️ CRITICAL: Premium/NAV Calculation Pitfall

**NEVER use `f[80]` as the premium rate.** This field is unreliable and can be wildly wrong. Always calculate premium manually using the official NAV.

**Correct premium calculation:**
```python
price = float(f[3])       # 场内交易价
nav = float(f[81])         # 官方最新净值 ✅ 这是正确的净值字段
# DO NOT use f[51] (IOPV估算) as NAV for premium calculation
premium = (price - nav) / nav * 100  # 正=溢价，负=折价
```

**Common mistake:** Taking `f[51]` (IOPV估算净值) as the NAV for premium calculation. IOPV is an intraday estimate that reflects current market moves of underlying assets. For QDII funds tracking US stocks, IOPV already bakes in overnight US market moves, so comparing price to IOPV gives a misleadingly small premium.

**Example from real session (160644 港美互联网LOF):**
| Field | Value | What it is |
|:------|:-----:|:-----------|
| f[3] price | 2.443 | 场内交易价 |
| f[51] IOPV | 2.471 | 实时估算净值（含昨晚美股涨幅） |
| f[81] NAV | 2.0105 | **官方最新净值** ← 正确基准 |
| price vs IOPV | -1.13% | 误以为是折价 ❌ |
| price vs f[81] | **+21.5%** | **真实溢价** ✅ |

The 21.5% premium meant the fund was trading far above its official NAV — extremely dangerous for chasing.

## 第一步：识别基金类型

| 特征 | LOF | ETF |
|:----|:----|:----|
| 代码格式 | 16xxxx（深交所） | 159xxx（深）, 51xxxx（沪） |
| 交易方式 | 场内场外均可 | 仅场内 |
| 净值揭示 | 盘中估算净值 available | 每15秒公布IOPV |
| 溢价/折价 | 常见（流动性差时更明显） | 较少（做市商套利） |

## 关键分析维度

### 1. 现价 vs 净值（溢价/折价）

从Tencent API解析（**注意正确字段**）：
- `f[3]` = 场内交易价
- `f[51]` = IOPV净值估算（盘中实时，反映当前成分股价格）
- `f[81]` = **官方最新净值**（基于前一日收盘成分股价格）✅ 计算溢价的正确基准
- `f[49]` = 量比
- 溢价率不直接取API字段，需自行计算：`(price - f[81]) / f[81] * 100`

**判断逻辑：**
- 溢价 > 5% → 场内情绪严重过热，风险极大
- 溢价 > 20% → 极端危险！溢价随时可能崩塌
- 折价 > 2% → 可能存在套利机会，或流动性不足
- 折价但大涨 → 净值确实在涨，不是炒作

### 2. 跟踪标的 / 成分股

LOF/ETF的涨跌取决于其跟踪的指数/资产，不是独立行情。需要查明：

```python
# 从名称推断跟踪方向
名称 = "港美互联网LOF"  # → 港股+美股互联网公司
名称 = "港股通科技30ETF"  # → 仅港股通科技股
```

**关键问题：今天涨的是哪部分？**
- 港美互联网LOF包含 **港股+美股中概股**
- 美股交易时间与A股/港股不同步（美股昨晚收盘）
- 所以160644今天暴涨可能是因为昨晚美股中概大涨，而港股今天在跌

### 2b. Tencent API LOF/ETF 字段映射（完整版）

| 字段 | 含义 | 备注 |
|:----:|:-----|:-----|
| f[3] | 场内交易价 | |
| f[4] | 昨收价（场内） | 不是净值 |
| f[32] | 涨幅% | 基于f[4]昨收价 |
| f[37] | 成交额（万元） | |
| f[38] | 换手率% | |
| f[49] | 量比 | |
| f[50] | 委差 | |
| f[51] | **IOPV净值估算** ⚠️ | 盘中实时估算，反映当前成分股价格。**不是计算溢价的正确基准** |
| f[81] | **官方最新净值** ✅ | 基于前一日成分股收盘价。**计算溢价的正确字段** |
| f[80] | 其他指标（非溢价率）⚠️ | 此字段不可靠，**不使用** |

**溢价计算（唯一正确方法）：**
```python
price = float(f[3])
nav = float(f[81])  # 只能用f[81]，不能用f[51]
premium = (price - nav) / nav * 100  # 正=溢价，负=折价
```

### 3. 换手率异常判断

LOF的正常换手率通常 < 5%。异常高换手（> 20%）说明：
- 游资炒作基金（类似炒股）
- 流动性陷阱：大资金进出造成价格剧烈波动
- 可能导致溢价/折价扩大

### 4. 与同类ETF对比

当用户同时持有/询问多个同类基金时（如159636 vs 160644）：

| 对比维度 | 基金A | 基金B | 差异来源 |
|:--------|:----:|:----:|:--------|
| 今日涨幅 | +7.85% | -1.98% | 美股中概 vs 仅港股 |
| 跟踪方向 | 港股+美股 | 仅港股 | 跨市场vs单市场 |
| 溢价率 | -0.81% | — | 净值驱动而非炒作 |
| 60日分位 | 95.2% | — | 接近前高 vs 低位 |

## ⚠️ 风险提示

1. **T+0 vs T+1 区分（重要！）**
   - **境内LOF/ETF**（跟踪A股/港股通）→ T+1，今天买入明天才能卖
   - **跨境QDII ETF/LOF**（跟踪港美股/海外市场）→ 部分为T+0，可在同一天买卖
   - **不要默认假设T+0或T+1** → 每次分析时需明确告知用户该基金是T+0还是T+1
   - 判断方法：查基金合同或从名称推断（含"港美"等跨境字样的多为QDII），但不100%确定时需提示"请以基金公告为准"

2. **净值≠交易价**：大幅溢价时买入，即使净值不动也可能亏钱。溢价>5%时风险显著加大

3. **流动性风险**：日成交额 < 5000万的LOF，买卖价差大，不适合短线

4. **跨市场时差**：含美股成分的基金，当日涨幅反映的是昨晚美股收盘，今晚美股走势未知

## 典型分析流程

当用户问到一个LOF/ETF代码时：

```python
# 1. 拉取实时数据
curl -s "https://qt.gtimg.cn/q=sz{code}"

# 2. 检查关键字段
f[1]   # 名称 → 推断跟踪方向
f[3]   # 现价
f[32]  # 涨幅%
f[37]  # 成交额(万)
f[38]  # 换手率%
f[51]  # IOPV净值估算（盘中实时）
f[81]  # ⭐ 官方最新净值 → 计算溢价的基准

# 3. 计算正确溢价（f[81]为基准）
price = float(f[3])
nav = float(f[81])
premium = (price - nav) / nav * 100  # 溢价率

# 4. ⚠️ 不要用f[51]算溢价
# f[51]是IOPV（已含当日成分股涨跌），用它算溢价会严重低估真实溢价

# 5. 判断风险级别
if premium > 20:
    print("⚠️ 极端溢价！价格远高于净值，追高风险极大")
elif premium > 10:
    print("⚠️ 高溢价，注意溢价收敛风险")
elif premium > 5:
    print("⚠️ 溢价偏高，谨慎参与")
else:
    print("✅ 溢价正常范围")

# 6. 检查60日分位判断位置
# 如果60日分位 > 90% ∧ 连续两天涨幅 > 15% → 高位加速，追高危险
```

### 快速判断模板

当用户给一个LOF代码时，输出结构：

```
名称: XXX（代码）
现价: X.XXX  +X.XX%  |  日高X.XXX 日低X.XXX
净值(官方): X.XXXX
溢价: +XX.X%  ← 价格比净值贵XX%
类型: [QDII跨境/境内] → [T+0/T+1]
判断: [净值驱动/溢价炒作/高位/低位]
```
