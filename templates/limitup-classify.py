#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涨停归类反推 —— 配套 SKILL.md「Step 2b: 涨停归类反推」与 references/扫描全覆盖.md 铁律三。

解决的问题：板块资金流按"绝对额"排序会系统性歧视小市值板块（旅游/传媒/农业/商贸），
导致它们即使拉出涨停集群也永远排不进榜单前六，被静默过滤。
2026-08-25 全天漏掉旅游板块（凯撒旅业涨停+10%、20只里18只上涨）即由此造成。

做法：不看资金额，直接拉全市场涨停股 → 用东财 f100 字段取所属行业 → 聚合计数
      → 凡 >=2 只涨停的方向一律列出，强制评估。

用法：
  PYTHONIOENCODING=utf-8 D:/Anaconda/python.exe templates/limitup-classify.py
  PYTHONIOENCODING=utf-8 D:/Anaconda/python.exe templates/limitup-classify.py --pct 7    # 放宽到涨幅>=7%

数据源：东方财富 push2delay（clist），f100=所属行业。push2 被封时 push2delay 通常仍可用。
"""

import json, sys, urllib.request
from collections import defaultdict

MIN_PCT = 9.5          # 视为"涨停/接近涨停"的阈值(%)
MIN_COUNT = 2          # 板块内达到几只就强制评估
UA = {"User-Agent": "Mozilla/5.0"}
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"      # 深主板+创业板+沪主板+科创板
UT = "bd1d9ddb04089700cf9c27f6f7426281"


def flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8")


def fetch_all():
    """按涨幅倒序翻页，直到跌破阈值即停 —— 不必拉全市场5500只。"""
    rows, pn = [], 1
    while pn <= 12:
        url = (f"https://push2delay.eastmoney.com/api/qt/clist/get?cb=j&pn={pn}&pz=100"
               f"&po=1&np=1&ut={UT}&fields=f2,f3,f12,f14,f100,f20&fid=f3&fs={FS}")
        txt = get(url)
        txt = txt[txt.index("(") + 1: txt.rindex(")")]
        data = json.loads(txt).get("data")
        if not data:
            break
        diff = data["diff"]
        rows += diff
        # 本页最后一只已跌破阈值 → 后面都不用看了
        last = diff[-1].get("f3")
        if isinstance(last, int) and last / 100.0 < MIN_PCT:
            break
        pn += 1
    return rows


def is_tradable(r):
    """剔除 ST / 退市 / 新股次新(N、C开头) / 科创板(用户无权限)"""
    name = str(r.get("f14", ""))
    code = str(r.get("f12", ""))
    if "ST" in name or "退" in name:
        return False
    if name.startswith(("N", "C")):
        return False
    if code.startswith("688"):
        return False
    return True


def main():
    global MIN_PCT
    MIN_PCT = float(flag("--pct", MIN_PCT))

    rows = fetch_all()
    ups = []
    for r in rows:
        p = r.get("f3")
        if not isinstance(p, int):
            continue
        if p / 100.0 < MIN_PCT:
            continue
        if not is_tradable(r):
            continue
        ups.append({
            "name": r["f14"], "code": r["f12"],
            "pct": p / 100.0,
            "sector": r.get("f100") or "未归类",
            "mktcap": (r.get("f20") or 0) / 1e8,   # 总市值(亿)
        })

    if not ups:
        print(f"今日无涨幅>={MIN_PCT}%的可交易标的（已剔除ST/688/新股）")
        return

    by = defaultdict(list)
    for u in ups:
        by[u["sector"]].append(u)

    ordered = sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    hot = [(s, v) for s, v in ordered if len(v) >= MIN_COUNT]
    single = [(s, v) for s, v in ordered if len(v) < MIN_COUNT]

    print(f"涨幅>={MIN_PCT}% 可交易标的 {len(ups)} 只，覆盖 {len(by)} 个行业")
    print("=" * 68)
    print(f"🔴 强制评估（>={MIN_COUNT}只涨停的方向，共 {len(hot)} 个）")
    print("   —— 无论资金流入多少、无论在不在板块排名前六，一律单独评估")
    print("=" * 68)
    for s, v in hot:
        caps = [x["mktcap"] for x in v if x["mktcap"]]
        capinfo = f"  中位市值 {sorted(caps)[len(caps)//2]:.0f}亿" if caps else ""
        print(f"\n【{s}】{len(v)}只{capinfo}")
        for x in sorted(v, key=lambda y: -y["pct"]):
            print(f"    {x['pct']:+6.2f}%  {x['name']:<8} {x['code']}  {x['mktcap']:.0f}亿")

    if single:
        print("\n" + "-" * 68)
        print(f"⚪ 单只涨停（{len(single)}个方向）—— 多为个股利好,非板块行情,可不深挖")
        print("   " + "、".join(f"{s}({v[0]['name']})" for s, v in single[:25]))

    print("\n" + "=" * 68)
    print("📌 输出到正文时,必须写一行「今日涨停归类」列出上述所有🔴方向及只数。")
    print("   评估后否决可以,沉默不提不行 —— 沉默会让用户以为框架没看见。")


if __name__ == "__main__":
    main()
