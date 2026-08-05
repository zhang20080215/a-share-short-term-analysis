# API调用模式与常见问题 (2026-07-14)

## akshare Python环境

当前环境:
- 系统Python: `/usr/bin/python3.12` (akshare安装在此)
- Hermes venv: `/home/agentuser/.hermes/hermes-agent/venv/bin/python3` (Python 3.11, 无akshare)
- 安装方式: `pip3 install akshare --break-system-packages`
- **始终用 `python3.12` 运行akshare脚本**，不要用 `python3`

## 数据源可靠性

东方财富API (`push2his.eastmoney.com`, `push2.eastmoney.com`) 频繁断开连接，尤其是：
- 全市场数据 (`stock_zh_a_spot_em`) — 5000+条数据，最容易断连
- 概念板块映射 (`stock_board_concept_name_em`) — 有时成功有时失败
- **2026-07-14: 东财API全天不可用，完全依赖腾讯API完成选股**

### 重试模式

```python
for attempt in range(3):
    try:
        df = ak.some_function(...)
        break
    except Exception as e:
        if attempt < 2:
            time.sleep(2)
```

关键: 不要因为一次失败就放弃整个扫描。

### 备用方案

### 优先级顺序

1. **akshare** — 首选，数据最全（板块列表+成分股+K线+全市场）
2. **腾讯行情 (qt.gtimg.cn)** — akshare全面故障时的可靠替代：实时报价、ETF行情、大盘指数
3. **腾讯K线 (web.ifzq.gtimg.cn)** — 个股历史K线，akshare/东方财富K线中断时使用。格式: `?param=sh601899,day,,,60,qfq`
4. **baostock** — 仅EOD数据（T-1），无实时价格，作为K线补充
5. **不要用错误/过期数据** — 用户明确要求数据失败时抛异常；**严禁混合不同时间戳/不同数据源的数据做对比分析**

### 东方财富API全面断连记录

**2026-07-14:** push2.eastmoney.com + push2his.eastmoney.com 全天不可用（`RemoteDisconnected`）。akshare行业/概念板块 + 成分股 + K线全部失败。**当天完全依赖腾讯系API完成选股。** 腾讯ETF行情(qt.gtimg.cn) + 腾讯K线(web.ifzq.gtimg.cn) = 完整选股数据链。

### 腾讯K线 API (web.ifzq.gtimg.cn)

当东方财富K线不可用时，这是可靠替代：

```python
import urllib.request, json

# 个股日K线（前复权），最近60日
url = 'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh601899,day,,,60,qfq'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
raw = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
data = json.loads(raw)

# 数据在 data -> {code} -> qfqday (前复权) 或 day (不复权)
k = None
for key in data.get('data', {}):
    k = data['data'][key].get('qfqday') or data['data'][key].get('day')
    if k: break

# 每条: [日期, 开, 收, 高, 低, 成交量]
for x in k[-5:]:
    date, o, c, h, l, vol = x[0], float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])
```

**关键陷阱：**
- 参数中的code格式：`sh601899`（沪深前缀+SZ/SH代码），不是纯数字
- 返回的key可能带前缀或纯数字，需要遍历查找
- 分离线类型：`qfqday`(前复权) / `day`(不复权) / `hfqday`(后复权)

### 腾讯实时行情 API (qt.gtimg.cn)

当 akshare 全面断连时，这是最可靠的实时行情源：

```python
import subprocess

def tq(codes):
    \"\"\"批量获取腾讯实时行情。codes: 'sh000001,sz399001,sz002156'\"\"\"
    r = subprocess.run(['curl','-s',f'https://qt.gtimg.cn/q={codes}'],
                       capture_output=True, timeout=10)
    raw = r.stdout.decode('gbk', errors='replace')  # 腾讯返回GBK编码
    res = {}
    # 腾讯返回的code不带前缀（sh000001 → 000001），需映射回去
    code_map = {c[2:]: c for c in codes.split(',')}
    for line in raw.split('\\n'):
        if '~' not in line: continue
        p = line.split('\"')[1].split('~') if '\"' in line else line.split('~')
        if len(p) < 10: continue
        bare = p[2]
        orig = code_map.get(bare, bare)
        try:
            h = float(p[33]) if len(p)>33 and p[33] else 0
            l = float(p[34]) if len(p)>34 and p[34] else 0
        except: h = l = 0
        res[orig] = {'n': p[1], 'p': float(p[3]), 'pc': float(p[4]), 'h': h, 'l': l}
    return res
```

**关键陷阱：**
- 编码：腾讯返回 **GBK**，必须 `decode('gbk', errors='replace')`
- 代码映射：请求用 `sh000001`，返回数据中code是 `000001`（无前缀），必须做映射
- 批量：一次最多约60个代码，超出需分批

### ETF实时行情 = 板块强度代理

**腾讯板块数据(pt012xxx)经常滞后/错误**（显示+3.7%但成分股全跌）。用行业ETF替代：

```python
# ETF代码 → 板块映射
etf_map = {
    'sh512800': '银行', 'sh512880': '证券', 'sh512480': '半导体',
    'sz159995': '芯片', 'sh512010': '医药', 'sh512170': '医疗',
    'sh515790': '光伏', 'sh515030': '新能源车', 'sh512660': '军工',
    'sh512690': '酒', 'sh512400': '有色', 'sh512200': '房地产',
    'sh512980': '传媒', 'sh515880': '通信', 'sh516160': '新能源',
    'sh512100': '中证1000', 'sh510050': '上证50', 'sh510300': '沪深300',
}
# 拉取所有ETF行情，按涨幅排序即得板块强度排名
```

**优势：** ETF实时交易，数据准确反映板块资金流向，不存在滞后问题。

### 数据时间戳一致性铁律

**2026-07-13 教训：** 用上午akshare的板块数据+下午腾讯的个股数据做对比→板块排名完全错乱（中药→汽车切换），被用户当脸纠正"数据都不对"。

**规则：**
1. 每次"全局选股"必须所有数据来自同一时间窗口
2. 如果中途API断了，重新全量拉取而不是补充缺失部分
3. 不同数据源（akshare vs 腾讯）的板块数据**不可互相对比**——分类体系不同

## 板块API对照表

| 数据 | 函数 | 备注 |
|------|------|------|
| 行业板块列表(涨幅排名) | `stock_board_industry_name_em()` | 稳定 |
| 概念板块列表(涨幅排名) | `stock_board_concept_name_em()` | 稳定 |
| 行业板块成分股 | `stock_board_industry_cons_em(symbol='板块名')` | 部分板块名会报IndexError |
| 概念板块成分股 | `stock_board_concept_cons_em(symbol='板块名')` | 部分板块名会报IndexError |
| 个股历史K线 | `stock_zh_a_hist(symbol='代码', period='daily', adjust='qfq')` | 稳定，支持重试 |
| 全市场实时 | `stock_zh_a_spot_em()` | 极不稳定，避免频繁调用 |
| 指数K线 | `stock_zh_index_daily_em(symbol='sh000001')` | 一般稳定 |

### 板块成分股失败的替代方案

当 `stock_board_industry_cons_em(symbol='中药')` 返回 `IndexError: index 0 is out of bounds` 时：
- 部分板块名在新版akshare中需要不同的symbol格式
- 优先使用 `stock_board_concept_cons_em` (概念板块函数兼容性更好)
- 如果两个都失败，用板块级别数据（涨跌家数、换手率）做判断，放弃该板块的个股初筛

## Python编码陷阱

**问题**: 在 `python3 -c "..."` 中包含中文字符会导致引号解析错误。
```python
# ❌ 这会在引号嵌套时出错
terminal("python3 -c \"print('中药')\"")
# SyntaxError: '(' was never closed
```

**解决方案**: 将代码写入临时脚本文件，再执行。
```python
write_file("/tmp/scan.py", content=code)
terminal("python3.12 /tmp/scan.py")
```

使用 `execute_code` + `terminal()` 时同理：不要在 inline `-c` 中混用中英文引号。

## execute_code 并行模式

选股扫描涉及多个独立数据源（大盘+行业+概念+情绪），使用 `execute_code` 批量调用 `terminal()`：

```python
from hermes_tools import terminal

# 四个独立调用在execute_code内部并行执行
idx = terminal("python3.12 /tmp/get_index.py", timeout=30)
ind = terminal("python3.12 /tmp/get_industry.py", timeout=30)
concept = terminal("python3.12 /tmp/get_concept.py", timeout=30)
breadth = terminal("python3.12 /tmp/get_breadth.py", timeout=60)
```

比逐个 tool call 快 3-4 倍，且不需要等待每个结果才开始下一个。
