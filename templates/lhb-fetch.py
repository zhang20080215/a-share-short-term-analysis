#!/usr/bin/env python3
"""
龙虎榜抓取 — 配套 references/龙虎榜与席位分析.md 使用。

功能：拉指定交易日的龙虎榜列表（按净额排序），用于验证"这波谁在买"。
- Hermes 首选 akshare（席位明细更全）
- 无 akshare 时降级东财 datacenter API（curl，已验证可达）

用法：python3 lhb-fetch.py [YYYY-MM-DD]   不带参数=今天
"""

import sys, json, urllib.request, urllib.parse
from datetime import date

DATE = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
TOP_N = 30


def try_akshare(d):
    """Hermes 首选。返回列表或 None。"""
    try:
        import akshare as ak
        ymd = d.replace("-", "")
        df = ak.stock_lhb_detail_em(start_date=ymd, end_date=ymd)
        if df is None or df.empty:
            return None
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "code": str(r.get("代码", "")),
                "name": str(r.get("名称", "")),
                "net":  float(r.get("龙虎榜净买额", 0) or 0),
                "amt":  float(r.get("龙虎榜成交额", 0) or 0),
                "why":  str(r.get("上榜原因", "")),
            })
        return rows
    except Exception as e:
        print(f"[akshare 不可用，降级东财API] {e}", file=sys.stderr)
        return None


def try_eastmoney(d):
    """降级：东财 datacenter API。"""
    base = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLANATION,BILLBOARD_NET_AMT,ACCUM_AMOUNT",
        "filter": f"(TRADE_DATE='{d}')",
        "sortColumns": "BILLBOARD_NET_AMT", "sortTypes": "-1",
        "pageSize": "50", "pageNumber": "1", "source": "WEB", "client": "WEB",
    }
    url = base + "?" + urllib.parse.urlencode(params)
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8")
            data = (json.loads(raw).get("result") or {}).get("data")
            if not data:
                return None
            return [{
                "code": r["SECURITY_CODE"], "name": r["SECURITY_NAME_ABBR"],
                "net": float(r.get("BILLBOARD_NET_AMT") or 0),
                "amt": float(r.get("ACCUM_AMOUNT") or 0),
                "why": r.get("EXPLANATION", ""),
            } for r in data]
        except Exception:
            continue
    return None


def main():
    rows = try_akshare(DATE) or try_eastmoney(DATE)
    if not rows:
        print(f"{DATE} 无龙虎榜数据（可能非交易日/尚未收盘发布）")
        return
    rows.sort(key=lambda x: x["net"], reverse=True)
    print(f"=== 龙虎榜 {DATE}（按净买额排序，Top {TOP_N}）===")
    for r in rows[:TOP_N]:
        arrow = "🟢买" if r["net"] >= 0 else "🔴卖"
        print(f"{arrow} {r['net']/1e8:+.2f}亿  {r['name']}({r['code']})  "
              f"成交{r['amt']/1e8:.1f}亿  [{r['why'][:20]}]")
    print("\n提示：净买为正且占成交额比例大=有资金主导；"
          "看单只席位明细用 ak.stock_lhb_stock_detail_em(symbol,date,flag)。")


if __name__ == "__main__":
    main()
