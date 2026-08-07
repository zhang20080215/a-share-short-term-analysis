#!/usr/bin/env python3
"""
持仓账本 — 配套 references/持仓账本与schema.md。

一处维护持仓(代码/成本/股数/止损/止盈)，运行后：
拉实时行情+K线 → 算浮盈、距止损/止盈%、20日区间位置(接高抛低吸章) → 异动预警。
替代每次手动重述持仓；可挂 cronjob 定时推送(见 closing-check.py 的 cronjob 示例)。

用法：python3 portfolio-ledger.py [positions.json]
  不带参数用下方 POSITIONS。positions.json 格式见 references/持仓账本与schema.md。
"""

import sys, json, subprocess, urllib.request
from datetime import date

STALE_DAYS = 5  # 呆滞判定的最短持有天数（见 references/资金效率与轮动纪律.md §2）

# ====== 持仓（也可用 positions.json 覆盖）======
# 元组尾部两项为 opened_date(YYYY-MM-DD)、type("长线底仓"/"短线仓")，可留空。
POSITIONS = [
    # code,       name,     cost,  shares, stop,  target, opened_date,  type
    ("sh600900", "长江电力", 25.90, 400,  26.27, 30.00, "2026-06-01", "长线底仓"),
    ("sh600150", "中国船舶", 34.15, 300,  31.80, 40.00, "2026-07-20", "长线底仓"),
    ("sh600309", "万华化学", 70.81, 400,  66.48, 82.00, "2026-06-15", "长线底仓"),
]
# ============================================


def load_positions():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            return [(p["code"], p["name"], p["cost"], p["shares"],
                     p.get("stop", 0), p.get("target", 0),
                     p.get("opened_date", ""), p.get("type", ""))
                    for p in json.load(f)]
    return POSITIONS


def _iter8(positions):
    """把持仓元组补齐到 8 项(兼容旧的 6 项 positions.json)：
    code,name,cost,shares,stop,target,opened_date,type。"""
    for p in positions:
        p = tuple(p)
        if len(p) < 8:
            p = p + ("",) * (8 - len(p))
        yield p[:8]


def held_days(opened_date):
    """持有天数（自然日近似）；无日期返回 None。"""
    if not opened_date:
        return None
    try:
        y, m, dd = (int(x) for x in opened_date.split("-"))
        return (date.today() - date(y, m, dd)).days
    except Exception:
        return None


def realtime(codes):
    r = subprocess.run(["curl", "-s", "--max-time", "10",
                        f"https://qt.gtimg.cn/q={codes}"],
                       capture_output=True, timeout=12)
    raw = r.stdout.decode("gbk", errors="replace")
    out = {}
    for line in raw.split("\n"):
        if "~" not in line:
            continue
        f = line.split('"')[1].split("~") if '"' in line else line.split("~")
        if len(f) < 36:
            continue
        code = f[2]
        out[code] = {"price": float(f[3]), "prev": float(f[4]),
                     "high": float(f[34]), "low": float(f[35])}
    return out


def kline_band(code):
    """返回 (20日低, 20日高, MA5, MA20)。"""
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={code},day,,,60,qfq")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=12).read().decode())["data"]
    k = None
    for key in d:
        if isinstance(d[key], dict):
            k = d[key].get("qfqday") or d[key].get("day")
            if k:
                break
    closes = [float(x[2]) for x in k]
    highs = [float(x[3]) for x in k]
    lows = [float(x[4]) for x in k]
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    return min(lows[-20:]), max(highs[-20:]), ma5, ma20


def main():
    positions = load_positions()
    codes = ",".join(p[0] for p in positions)
    rt = realtime(codes)
    total_cost = total_mv = 0
    print(f"{'标的':<8}{'现价':>7}{'浮盈%':>8}{'距止损':>8}{'距止盈':>8}{'区间位':>8}  预警")
    print("-" * 66)
    for code, name, cost, shares, stop, target, opened, ptype in _iter8(positions):
        bare = code[2:]
        q = rt.get(bare)
        if not q:
            print(f"{name:<8} 行情拉取失败"); continue
        price = q["price"]
        pl = (price - cost) / cost * 100
        to_stop = (price - stop) / price * 100 if stop else 0
        to_tgt = (target - price) / price * 100 if target else 0
        try:
            l20, h20, ma5, ma20 = kline_band(code)
            band = (price - l20) / (h20 - l20) * 100 if h20 > l20 else 0
        except Exception:
            band = -1
        # 预警
        w = []
        if stop and price <= stop:      w.append("🔴触及止损")
        if target and price >= target:  w.append("🎯触及止盈")
        if q["prev"] and (price - q["prev"]) / q["prev"] * 100 <= -5: w.append("⚠️大跌")
        if band >= 80:                  w.append("📈高抛区")
        elif 0 <= band < 20:            w.append("📉低吸区")
        # 🐌 呆滞短线仓：短线仓 + 持有久 + 浮盈卡平 + 卡区间中位（跑输板块/无催化需人工确认）
        hd = held_days(opened)
        if (ptype == "短线仓" and hd is not None and hd >= STALE_DAYS
                and -3 <= pl <= 3 and 30 <= band < 70):
            w.append(f"🐌呆滞({hd}天,待确认跑输板块→评估换仓)")
        bs = f"{band:.0f}%" if band >= 0 else "n/a"
        print(f"{name:<8}{price:>7.2f}{pl:>+7.1f}%{to_stop:>+7.1f}%{to_tgt:>+7.1f}%{bs:>8}  {' '.join(w)}")
        total_cost += cost * shares
        total_mv += price * shares
    print("-" * 66)
    tpl = (total_mv - total_cost) / total_cost * 100 if total_cost else 0
    print(f"组合市值 {total_mv:,.0f}元  总浮盈 {total_mv-total_cost:+,.0f}元 ({tpl:+.1f}%)")


if __name__ == "__main__":
    main()
