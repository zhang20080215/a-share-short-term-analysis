#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场情绪温度计 — 配套 references/情绪周期与自动模式路由.md。

把 Step 2a(CLS 涨停分析)已提取的广度/连板/封板/炸板/隔日溢价数字，合成 0-100 情绪温度分，
映射到 6 个周期阶段，输出 {建议默认模式, 仓位水位, 追热门尺度} + 护栏判定。

用法：
  python3 emotion-temp.py --json '{...}'          # 传入当日各指标
  python3 emotion-temp.py                          # 用下方 SAMPLE 演示

输入字段（缺省见 SAMPLE，缺则按中性值兜底）：
  limit_up        涨停家数
  limit_down      跌停家数
  max_streak      最高连板高度(板)
  seal_rate       封板率 %(0-100)
  broken_rate     炸板率 %(0-100)  —— 退潮先行信号
  yst_limit_perf  昨日涨停股今日平均涨幅 %  —— 赚钱效应，权重最高
  adv_dec_ratio   涨跌家数比(涨/跌)
  prev_score      昨日情绪温度分(可选，判退潮用)
  index_2day_crash  大盘单日-1.5%×连续2日(bool，硬护栏)
  account_drawdown  账户回撤 %(负数，如 -9；硬护栏)
"""

import sys, json

SAMPLE = {
    "limit_up": 42, "limit_down": 6, "max_streak": 3,
    "seal_rate": 72, "broken_rate": 25, "yst_limit_perf": 1.5,
    "adv_dec_ratio": 2.0, "prev_score": 58,
    "index_2day_crash": False, "account_drawdown": 0.0,
}

WEIGHTS = {"breadth": 0.20, "height": 0.15, "seal": 0.15,
           "broken": 0.10, "money": 0.25, "adv_dec": 0.15}


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def lin(x, x0, x1):
    """把 x 从 [x0,x1] 线性映射到 [0,100]，超出裁剪。"""
    if x1 == x0:
        return 50.0
    return clamp((x - x0) / (x1 - x0) * 100.0)


def height_score(streak):
    table = {0: 0, 1: 20, 2: 40, 3: 55, 4: 70, 5: 82, 6: 90}
    if streak >= 7:
        return 100.0
    return float(table.get(int(streak), 0))


def sub_scores(d):
    net = d["limit_up"] - d["limit_down"]
    return {
        "breadth": lin(net, -30, 80),
        "height": height_score(d["max_streak"]),
        "seal": clamp(d["seal_rate"]),
        "broken": clamp(100 - d["broken_rate"]),
        "money": lin(d["yst_limit_perf"], -5, 5),   # 0%→50, ±5%→端点
        "adv_dec": lin(d["adv_dec_ratio"], 0.33, 3.0),
    }


def temperature(d):
    s = sub_scores(d)
    return sum(s[k] * WEIGHTS[k] for k in WEIGHTS), s


# 阶段 → (建议默认模式, 仓位水位, 追热门尺度, 是否允许自动激进)
PHASES = [
    (15, "冰点/退潮末", "低估值/空仓", "≤3成", "禁", False),
    (35, "修复期",     "默认+试仓",   "3-5成", "龙头首板试", False),
    (55, "发酵期",     "成长/激进并行", "5-7成", "敢打低吸", True),
    (75, "主升期",     "激进为主",     "7-8成", "大胆追龙头", True),
    (101, "高潮期",    "收(不追跟风)",  "开始减", "只做龙头分歧", False),
]


def classify(score, d):
    # 退潮期覆盖：温度掉头(↓5分+) 且 炸板率高(≥40)
    prev = d.get("prev_score")
    if prev is not None and score < prev - 5 and d["broken_rate"] >= 40:
        return ("退潮期", "防守", "快速降", "禁,兑现", False)
    for hi, name, mode, level, chase, allow_aggr in PHASES:
        if score < hi:
            return (name, mode, level, chase, allow_aggr)
    return PHASES[-1][1:]


def guardrails(d, phase_name, allow_aggr):
    """返回 (最终能否自动激进, 护栏说明列表)。硬护栏压过一切。"""
    notes = []
    hard = False
    if d.get("index_2day_crash"):
        notes.append("硬-1 大盘暴跌规则(-1.5%×2日) → 强制不开新仓/保守")
        hard = True
    if d.get("account_drawdown", 0) <= -8:
        notes.append(f"硬-2 回撤熔断({d['account_drawdown']:.0f}%) → 强制保守")
        hard = True
    if phase_name in ("高潮期", "退潮期"):
        notes.append(f"硬-3 {phase_name} → 禁止自动激进(防派发段追高)")
    # 软护栏(温度掉头+炸板率升)在 main() 里单独判，便于用最终 score
    return hard, notes


def main():
    d = dict(SAMPLE)
    if "--json" in sys.argv:
        d.update(json.loads(sys.argv[sys.argv.index("--json") + 1]))
    # 中性兜底
    for k, v in SAMPLE.items():
        d.setdefault(k, v)

    score, s = temperature(d)
    phase, mode, level, chase, allow_aggr = classify(score, d)
    hard, notes = guardrails(d, phase, allow_aggr)

    # 软护栏：温度掉头 + 炸板率升 → 降一档
    prev = d.get("prev_score")
    if prev is not None and score < prev - 5 and d["broken_rate"] >= 30 \
            and phase not in ("高潮期", "退潮期"):
        notes.append("软-1 温度掉头+炸板率升 → 激进度/仓位各降一档")

    # 最终姿态：硬护栏触发 → 强制保守；否则按阶段(高潮/退潮不自动激进)
    if hard:
        final_mode = "强制保守/不开新仓"
        final_aggr = False
    elif not allow_aggr:
        final_mode = mode
        final_aggr = False
    else:
        final_mode = mode
        final_aggr = True

    print("=" * 56)
    print(f"情绪温度 {score:.0f} / {phase}")
    print("-" * 56)
    for k in WEIGHTS:
        print(f"  {k:<8} {s[k]:5.0f}  ×{WEIGHTS[k]:.2f}")
    print("-" * 56)
    print(f"建议默认模式 : {final_mode}")
    print(f"仓位水位     : {level}")
    print(f"追热门尺度   : {chase}")
    print(f"自动激进     : {'是' if final_aggr else '否'}")
    if notes:
        print("护栏触发     :")
        for n in notes:
            print(f"  - {n}")
    else:
        print("护栏触发     : 无")
    print("=" * 56)
    print("声明模板： 情绪温度 {:.0f} / {} → {}，仓位水位 {} [护栏：{}]".format(
        score, phase, final_mode, level, "、".join(notes) if notes else "无触发"))


if __name__ == "__main__":
    main()
