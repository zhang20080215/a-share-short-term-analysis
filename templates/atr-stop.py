#!/usr/bin/env python3
"""
ATR自适应止损 + 风险反推仓位 计算器
配套 references/资金管理体系.md 使用。

功能：拉60日K线 → 算ATR(14) → 给出建议止损价 → 按风险预算反推股数。
解决"固定3-5%止损在高波动票上被反复洗出"的问题。

使用方法：
1. 修改下方 ACCOUNT / RISK_PCT / ATR_MULT / STOCKS
2. 运行：python3 atr-stop.py
   （Hermes环境有python3；本机Claude Code无python，用PowerShell等价核对）

数据源：腾讯K线 web.ifzq.gtimg.cn（无需akshare，最稳）。
K线字段顺序：[日期, 开, 收, 高, 低, 量]  —— 注意是 O/C/H/L，H和L在C后面。
"""

import urllib.request, json, sys

# ====== 修改以下配置 ======
ACCOUNT   = 200000      # 账户总值（元）
RISK_PCT  = 1.5         # 单笔风险预算占账户%（1-2%，保守1、激进2）
ATR_MULT  = 2.0         # 止损 = 入场 - ATR_MULT×ATR（1.5紧/2常规/2.5-3趋势）
STOCKS = [
    ("sz300346", "南大光电"),
    ("sh600584", "长电科技"),
    ("sh600900", "长江电力"),
]
# ==========================

RISK_BUDGET = ACCOUNT * RISK_PCT / 100


def fetch_kline(code, days=60):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={code},day,,,{days},qfq")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8")
    data = json.loads(raw)["data"]
    for key in data:
        if isinstance(data[key], dict):
            k = data[key].get("qfqday") or data[key].get("day")
            if k:
                return k
    return None


def atr(kline, period=14):
    """TrueRange的period日均值。kline每行[日期,开,收,高,低,量]。"""
    trs = []
    for i in range(1, len(kline)):
        high = float(kline[i][3]); low = float(kline[i][4])
        prev_close = float(kline[i-1][2])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def main():
    print(f"账户 {ACCOUNT:,} | 单笔风险预算 {RISK_PCT}% = {RISK_BUDGET:,.0f}元 "
          f"| 止损 = 入场 - {ATR_MULT}×ATR(14)\n" + "-" * 72)
    for code, name in STOCKS:
        try:
            k = fetch_kline(code)
            if not k:
                print(f"{name}({code}): K线解析失败"); continue
            entry = float(k[-1][2])                 # 最新收盘作入场参考
            a = atr(k, 14)
            if a is None:
                print(f"{name}({code}): 数据不足14日"); continue
            stop = entry - ATR_MULT * a
            stop_dist = (entry - stop) / entry       # 止损距离%
            pos_amt = RISK_BUDGET / stop_dist        # 仓位金额
            pos_amt = min(pos_amt, ACCOUNT * 0.30)   # 单票≤30%上限
            shares = int(pos_amt / entry / 100) * 100
            real_risk = shares * (entry - stop)
            print(f"{name}({code}): 入场{entry:.2f} ATR{a:.2f} "
                  f"止损{stop:.2f}(-{stop_dist*100:.1f}%) → "
                  f"建议{shares}股 仓位{shares*entry:,.0f}元({shares*entry/ACCOUNT*100:.0f}%) "
                  f"实际风险{real_risk:,.0f}元")
        except Exception as e:
            print(f"{name}({code}): ERR {e}")


if __name__ == "__main__":
    main()
