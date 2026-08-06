# 持仓账本与 schema（持仓状态持久化）

> **2026-08-06 新增。** 框架假设有 memory/session 存持仓，但实际常常是空的——每次要用户重述。
> 一个真实操盘台需要**持久的持仓账本**：代码/成本/股数/止损/止盈，一处维护、自动跟踪。
> 工具：`templates/portfolio-ledger.py`。相关：SKILL.md「长线底仓的波段管理」、[[资金管理体系]]。

---

## 1. positions.json 格式

`portfolio-ledger.py` 可读该文件（不传参则用脚本内 POSITIONS）：
```json
[
  {"code": "sh600900", "name": "长江电力", "cost": 25.90, "shares": 400, "stop": 26.27, "target": 30.00},
  {"code": "sh600150", "name": "中国船舶", "cost": 34.15, "shares": 300, "stop": 31.80, "target": 40.00},
  {"code": "sh600309", "name": "万华化学", "cost": 70.81, "shares": 400, "stop": 66.48, "target": 82.00}
]
```
- `code`：带 sh/sz 前缀。`stop`/`target` 可省略（省略则不算距止损/止盈）。
- 止损价建议由 [[资金管理体系]] 的 ATR 法(`atr-stop.py`)算出后填入。

## 2. 运行输出（已验证）
```
标的       现价   浮盈%   距止损  距止盈  区间位  预警
长江电力  27.76  +7.2%   +5.4%   +8.1%   34%
中国船舶  34.89  +2.2%   +8.9%  +14.6%   51%
万华化学  74.73  +5.5%  +11.0%   +9.7%   82%  📈高抛区
组合市值 51,463元  总浮盈 +2,534元 (+5.2%)
```
- **区间位/高抛低吸预警**接 SKILL.md「长线底仓的波段管理」：≥80%=📈高抛区，<20%=📉低吸区。
- 其它预警：🔴触及止损、🎯触及止盈、⚠️当日大跌>5%。

## 3. Hermes memory 持仓 schema（持久化约定）

Hermes 端把持仓写入 memory，键名与字段固定，便于跨会话读取，避免每次重述：
```
memory key: portfolio/holdings
value(每条):
  code / name / cost / shares / stop / target
  opened_date        建仓日期(绝对日期)
  thesis             建仓逻辑一句话（用于中线评估验证）
  type               "长线底仓" | "短线仓"（决定走高抛低吸还是跟踪止盈）
  last_updated       最后更新时间
```
- **type 字段很关键**：决定出场走 [[止盈体系]](交易仓) 还是 SKILL.md 高抛低吸(底仓)。
- 每次调仓(加/减/T/换)后**立即更新 memory**，呼应"持仓信息比板块数据更容易过期"教训。

## 4. cronjob 定时推送
参考 `templates/closing-check.py` 的 cronjob 写法，把 `portfolio-ledger.py` 挂到收盘前(如14:30)自动拉持仓状态并推送，重点看：触及止损/止盈、进入高抛/低吸区的标的。
