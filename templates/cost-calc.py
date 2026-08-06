#!/usr/bin/env python3
"""
做T / 波段 交易成本计算器 — 配套 references/交易成本模型.md。

输出：毛利、成本拆项、净利、盈亏平衡差价、是否值得做。
用法：python3 cost-calc.py 买入价 卖出价 股数
  例：python3 cost-calc.py 2.27 2.30 2000
不带参数则用下方 DEMO 值。
"""

import sys

# 费率（2026现行，可按自己券商佣金调整）
COMMISSION = 0.00025   # 佣金 万2.5，双边
MIN_COMM   = 5.0       # 单边最低佣金5元
TRANSFER   = 0.00001   # 过户费 0.001%，双边
STAMP      = 0.0005    # 印花税 0.05%，仅卖出


def calc(buy, sell, shares):
    gross = (sell - buy) * shares

    buy_amt, sell_amt = buy * shares, sell * shares
    buy_comm  = max(buy_amt  * COMMISSION, MIN_COMM)
    sell_comm = max(sell_amt * COMMISSION, MIN_COMM)
    transfer  = (buy_amt + sell_amt) * TRANSFER
    stamp     = sell_amt * STAMP
    cost = buy_comm + sell_comm + transfer + stamp

    net = gross - cost
    # 盖住成本所需的最小价差（每股）
    breakeven_spread = cost / shares

    print(f"买入 {buy} × {shares}股 = {buy_amt:,.0f}元")
    print(f"卖出 {sell} × {shares}股 = {sell_amt:,.0f}元")
    print("-" * 48)
    print(f"毛利            {gross:+,.2f} 元")
    print(f"  买入佣金      -{buy_comm:,.2f}" + ("  (触及最低5元)" if buy_comm == MIN_COMM else ""))
    print(f"  卖出佣金      -{sell_comm:,.2f}" + ("  (触及最低5元)" if sell_comm == MIN_COMM else ""))
    print(f"  过户费        -{transfer:,.2f}")
    print(f"  印花税(卖)    -{stamp:,.2f}")
    print(f"  成本合计      -{cost:,.2f} 元")
    print("-" * 48)
    print(f"净利            {net:+,.2f} 元")
    print(f"盈亏平衡差价    {breakeven_spread:.4f} 元/股（差价低于此=净亏）")
    verdict = "✅ 值得做" if net > 0 else "❌ 净亏，不做"
    print(f"结论            {verdict}")


def main():
    if len(sys.argv) == 4:
        buy, sell, shares = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
    else:
        print("[DEMO] 用法: python3 cost-calc.py 买入价 卖出价 股数\n")
        buy, sell, shares = 2.27, 2.30, 2000
    calc(buy, sell, shares)


if __name__ == "__main__":
    main()
